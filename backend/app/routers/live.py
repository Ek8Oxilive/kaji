"""Flux temps réel (Server-Sent Events) de l'état d'un cluster."""
import asyncio
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..db import get_db, get_engine
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


async def stream(h: Hub, conn_id: int, fetch, heartbeat: float = HEARTBEAT) -> AsyncIterator[str]:
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
            yield sse(event, data)
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
async def events(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Instantané de l'état du cluster à chaque changement (nœuds, machines, quorum)."""
    _get_or_404(db, conn_id)
    db.close()                                   # libère la base avant de streamer
    return StreamingResponse(stream(hub, conn_id, make_fetch(conn_id, factory)), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
