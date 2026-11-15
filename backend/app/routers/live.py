"""Flux temps réel (Server-Sent Events) de l'état d'un cluster."""
import asyncio
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import roles, scope
from ..db import get_db, get_engine
from ..models import AdminUser
from ..deps import get_client_factory
from ..live import Hub, hub, sse
from .auth import current_user
from .cluster import Factory, _get_or_404, _params, http_error, shape_guests, shape_nodes, shape_status

router = APIRouter(tags=["live"], dependencies=[Depends(current_user)])
HEARTBEAT = 15.0


def make_fetch(conn_id: int, factory: Factory):
    """Construit la fonction d'interrogation : lit les identifiants à chaque tour (une connexion modifiée est prise en compte)."""
    async def fetch() -> dict:
        with Session(get_engine()) as db:       # session courte : jamais gardée ouverte pendant le flux
            params = _params(_get_or_404(db, conn_id))
        client = factory(**params)
        try:
            status, nodes, res = await asyncio.gather(
                client.get("/cluster/status"), client.get("/nodes"), client.get("/cluster/resources", type="vm"))
        except httpx.HTTPError as e:
            raise http_error(e)
        finally:
            await client.aclose()
        return {"status": shape_status(status), "nodes": shape_nodes(nodes), "guests": shape_guests(res)}
    return fetch


def scoped_fetch(fetch, conn_id: int, user_id: int):
    """Le même interrogateur, mais chaque instantané est réduit au périmètre du compte, RELU à chaque tour (un périmètre modifié ou retiré s'applique tout de suite).
    Si le périmètre a disparu entre-temps, plus rien n'est diffusé (jamais l'état complet)."""
    async def run() -> dict:
        snap = await fetch()
        with Session(get_engine()) as s:
            limits = scope.scope_of(s, user_id)
        if limits is None:
            return {"status": {"name": None, "quorate": None, "nodes": []}, "nodes": [], "guests": []}
        return scope.filter_snapshot(limits, conn_id, snap)
    return run


async def stream(h: Hub, conn_id: int | tuple[int, int], fetch, heartbeat: float = HEARTBEAT) -> AsyncIterator[str]:
    agen = h.subscribe(conn_id, fetch)
    nxt: asyncio.Future | None = None
    try:
        yield "retry: 3000\n\n"
        nxt = asyncio.ensure_future(agen.__anext__())
        while True:
            done, _ = await asyncio.wait({nxt}, timeout=heartbeat)
            if not done:
                yield ": ping\n\n"                # maintient la connexion ouverte à travers les proxys
                continue
            event, data = nxt.result()
            # « error » est déjà pris par EventSource (perte de connexion) : on émet « problem »
            yield sse("problem" if event == "error" else event, data)
            nxt = asyncio.ensure_future(agen.__anext__())
    finally:
        if nxt is not None and not nxt.done():
            nxt.cancel()                          # sinon aclose() échoue : « générateur déjà en cours »
            try:
                await nxt
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
        await agen.aclose()


@router.get("/api/connections/{conn_id}/events")
async def events(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Instantané de l'état du cluster à chaque changement (nœuds, machines, quorum)."""
    _get_or_404(db, conn_id)
    restricted = roles.normalize(user.role) != "admin" and scope.scope_of(db, user.id) is not None          # lu AVANT de libérer la base
    db.close()                                   # libère la base avant de streamer
    # Flux COMMUN à tous les utilisateurs de la connexion (un seul interrogateur) tant qu'ils utilisent le jeton partagé ; un utilisateur qui a SON jeton a son propre flux,
    # sinon l'état vu avec ses droits serait diffusé aux autres (et inversement).
    token_scope = getattr(factory, "scope_for", lambda _c: 0)(conn_id)
    key = conn_id if token_scope == 0 else (conn_id, token_scope)
    fetch = make_fetch(conn_id, factory)
    if restricted:                                                                                          # compte restreint : son propre canal, filtré (jamais le flux commun)
        key = (conn_id, token_scope, "scope", user.id)
        fetch = scoped_fetch(fetch, conn_id, user.id)
    return StreamingResponse(stream(hub, key, fetch), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
