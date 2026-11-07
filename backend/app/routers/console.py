"""Console web (noVNC, xterm.js) : demande d'une console, puis relais WebSocket vers Proxmox.

Chaque console est un accès interactif à une machine : tout est contrôlé côté serveur (session Kaji, `Origin`, identifiant à usage
unique lié à la session, cible construite par le serveur, limites). **Le ticket Proxmox n'apparaît jamais dans un journal, un
audit ou un message d'erreur.**
"""
import asyncio
import re
import time
from typing import Literal

import websockets
from fastapi import APIRouter, Depends, HTTPException, Path, Request, WebSocket, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import audit
from .. import db as dbm
from ..consolespec import (IDLE_TIMEOUT, MAX_DURATION, MAX_MESSAGE, SESSION_TTL, ConsoleSessions, Kind, Target, origin_ok,
                           valid_proxy_reply)
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from .actions import NODE
from .auth import _session_of, current_user
from .cluster import Factory, _px
from .connections import _get_or_404, _params

router = APIRouter(tags=["console"])

SESSIONS = ConsoleSessions()
WATCHDOG_EVERY = 5.0                       # secondes entre deux contrôles d'inactivité et de durée
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{20,64}")


class ConsoleBody(BaseModel):
    kind: Kind = "vnc"


def _audit(username: str, conn_id: int, action: str, target: str, st: str, detail: str | None = None) -> None:
    dbm.get_engine()
    with dbm._SessionLocal() as db:
        audit.record(db, username=username, connection_id=conn_id, action=action, target=target, status=st, detail=detail)


@router.post("/api/connections/{conn_id}/guests/{node}/{gtype}/{vmid}/console", status_code=status.HTTP_201_CREATED)
async def open_console(body: ConsoleBody, request: Request, conn_id: int, node: str = Path(pattern=NODE),
                       gtype: Literal["qemu", "lxc"] = Path(), vmid: int = Path(ge=100, le=999999999),
                       db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                       user: AdminUser = Depends(current_user)):
    """Demande une console. Renvoie un identifiant **à usage unique** (valable `SESSION_TTL` secondes, lié à ta session) à présenter
    au WebSocket `/api/console/{session}`. Pour noVNC (`vnc`), la réponse contient aussi le mot de passe VNC (le ticket, valable
    quelques secondes et une seule fois) ; pour xterm.js (`term`), le serveur s'en charge et le ticket ne quitte pas le serveur."""
    found = _session_of(request, db)
    owner = found[1].id if found else ""
    target = f"{gtype}/{vmid}@{node} ({body.kind})"

    def refuse(code: int, msg: str):
        audit.record(db, username=user.username, connection_id=conn_id, action="console-open", target=target, status="error", detail=msg)
        raise HTTPException(code, msg)

    if body.kind == "term" and gtype != "lxc":
        refuse(400, "La console texte (xterm.js) n'est disponible que pour les conteneurs")
    cur = await _px(db, factory, conn_id, "get", f"/nodes/{node}/{gtype}/{vmid}/status/current")
    if not isinstance(cur, dict) or cur.get("status") != "running" or cur.get("template"):
        refuse(409, "La machine doit être en marche (et ne pas être un modèle) pour ouvrir sa console")
    path = f"/nodes/{node}/{gtype}/{vmid}/{'vncproxy' if body.kind == 'vnc' else 'termproxy'}"
    try:
        reply = await _px(db, factory, conn_id, "post", path, **({"websocket": 1} if body.kind == "vnc" else {}))
    except HTTPException as e:
        audit.record(db, username=user.username, connection_id=conn_id, action="console-open", target=target, status="error", detail=str(e.detail))
        raise
    ok = valid_proxy_reply(reply, body.kind)
    if ok is None:
        refuse(502, "Réponse inattendue de Proxmox pour la console")
    port, ticket, pve_user = ok
    sid = SESSIONS.create(owner, Target(conn_id, node, gtype, vmid, body.kind, port, ticket, pve_user))
    if sid is None:
        refuse(429, "Trop de consoles demandées sans être ouvertes : réessaie dans quelques secondes")
    audit.record(db, username=user.username, connection_id=conn_id, action="console-open", target=target, status="started")
    return {"session": sid, "kind": body.kind, "expires_in": int(SESSION_TTL), **({"ticket": ticket} if body.kind == "vnc" else {})}


@router.websocket("/api/console/{session}")
async def console_ws(ws: WebSocket, session: str, factory: Factory = Depends(get_client_factory)):
    """Relais binaire navigateur <-> console Proxmox. Refus **avant** d'accepter (réponse HTTP 403) si l'`Origin`, la session
    Kaji ou l'identifiant ne conviennent pas."""
    if not origin_ok(ws.headers.get("origin"), ws.headers.get("host")) or not _SESSION_ID.fullmatch(session):
        await ws.close(code=1008)
        return
    dbm.get_engine()
    with dbm._SessionLocal() as db:
        found = _session_of(ws, db)
        if found is None:
            await ws.close(code=1008)
            return
        username, owner = found[0].username, found[1].id
        target = SESSIONS.take(session, owner)
        if target is None:
            await ws.close(code=1008)
            return
        try:
            client = factory(**_params(_get_or_404(db, target.conn_id)))
        except HTTPException:
            await ws.close(code=1011)
            return
    label = f"{target.gtype}/{target.vmid}@{target.node} ({target.kind})"
    url, headers, ctx = client.ws_target(f"/nodes/{target.node}/{target.gtype}/{target.vmid}/vncwebsocket",
                                         port=target.port, vncticket=target.ticket)
    await client.aclose()

    if not SESSIONS.acquire(owner):
        await ws.close(code=1013)
        return
    started, reason, up = time.monotonic(), "client", None
    try:
        subs = ws.scope.get("subprotocols") or []
        try:
            up = await websockets.connect(url, additional_headers=headers, ssl=ctx if url.startswith("wss:") else None,
                                          subprotocols=["binary"], max_size=MAX_MESSAGE, open_timeout=10, ping_interval=20, ping_timeout=20)
            if target.kind == "term":
                await up.send(f"{target.pve_user}:{target.ticket}\n")
                first = await asyncio.wait_for(up.recv(), 10)
                if (first.decode() if isinstance(first, bytes) else first)[:2] != "OK":
                    raise RuntimeError("terminal refusé")
        except Exception:                                    # le message d'origine peut contenir l'adresse (donc le ticket) : jamais renvoyé
            reason = "error: Proxmox injoignable ou console refusée"
            await ws.accept(subprotocol="binary" if "binary" in subs else None)
            await ws.close(code=1011)
            return
        await ws.accept(subprotocol="binary" if "binary" in subs else None)
        last = time.monotonic()

        async def to_proxmox() -> str:
            nonlocal last
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    return "client"
                data = msg.get("bytes") if msg.get("bytes") is not None else msg.get("text")
                if data is None:
                    continue
                if len(data) > MAX_MESSAGE:
                    await ws.close(code=1009)
                    return "message trop gros"
                try:
                    await up.send(data)
                except websockets.ConnectionClosed:
                    return "proxmox"
                last = time.monotonic()

        async def to_browser() -> str:
            nonlocal last
            try:
                async for m in up:
                    await (ws.send_bytes(m) if isinstance(m, bytes) else ws.send_text(m))
                    last = time.monotonic()
            except websockets.ConnectionClosed:
                pass
            return "proxmox"

        async def watchdog() -> str:
            while True:
                await asyncio.sleep(WATCHDOG_EVERY)
                now = time.monotonic()
                if now - last > IDLE_TIMEOUT:
                    return "inactivité"
                if now - started > MAX_DURATION:
                    return "durée maximale"

        tasks = [asyncio.create_task(f()) for f in (to_proxmox, to_browser, watchdog)]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            first_done = next(iter(done))
            reason = "error: relais interrompu" if first_done.exception() else first_done.result()
        finally:
            for t in tasks:
                t.cancel()
    finally:
        SESSIONS.release(owner)
        # L'audit d'abord : si le gestionnaire est interrompu pendant les fermetures ci-dessous (arrêt du serveur…), la fin de la
        # console est quand même journalisée.
        _audit(username, target.conn_id, "console-close", label, "error" if reason.startswith("error") else "ok",
               f"durée {int(time.monotonic() - started)} s · fin : {reason}")
        if up is not None:
            await up.close()
        try:
            await ws.close()
        except RuntimeError:
            pass                                             # déjà fermé
