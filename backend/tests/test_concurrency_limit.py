"""Limite de requêtes simultanées (lot #457) : refuser proprement (503) au lieu de tout bloquer quand la charge dépasse ce que le pool de base de données peut servir."""
import asyncio
import json
import logging
import time

import httpx
import pytest

from app.config import Settings, get_settings
from app.db import DB_POOL_OVERFLOW, DB_POOL_SIZE
from app.deps import get_base_client_factory
from app.limits import BODY, ConcurrencyLimit
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"


def run(coro, timeout: float = 5.0):
    """`asyncio.run` avec un délai maximal : un limiteur défaillant doit faire ÉCHOUER un test, pas le bloquer (les « portes » de ces tests ne s'ouvrent que si les autres requêtes finissent)."""
    async def bounded():
        return await asyncio.wait_for(coro, timeout)
    return asyncio.run(bounded())


def toy_app(gate: asyncio.Event, boom: bool = False):
    async def inner(scope, receive, send):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close"})
            return
        if boom:
            raise RuntimeError("panne")
        await gate.wait()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})
    return inner


async def call(asgi, path="/api/x", scope_type="http"):
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b""}
    await asgi({"type": scope_type, "path": path, "method": "GET", "headers": []}, receive, send)
    return sent


def status_of(sent):
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def test_over_the_limit_requests_get_an_immediate_503_with_retry_after_and_the_rest_keep_working():
    async def go():
        gate = asyncio.Event()
        mw = ConcurrencyLimit(toy_app(gate), limit=3)
        running = [asyncio.create_task(call(mw)) for _ in range(3)]
        await asyncio.sleep(0.05)
        assert mw.in_flight == 3
        t0 = time.perf_counter()
        shed = await call(mw)                                                       # la 4e : refusée TOUT DE SUITE, sans attendre les trois autres
        elapsed = time.perf_counter() - t0
        gate.set()
        done = await asyncio.gather(*running)
        after = await call(mw)                                                      # et dès qu'il y a de la place, tout repasse
        return shed, elapsed, [status_of(d) for d in done], status_of(after), mw
    shed, elapsed, done, after, mw = run(go())
    assert status_of(shed) == 503 and elapsed < 0.05 and done == [200, 200, 200] and after == 200
    headers = dict(next(m["headers"] for m in shed if m["type"] == "http.response.start"))
    assert headers[b"retry-after"] == b"2" and headers[b"content-type"] == b"application/json" and headers[b"cache-control"] == b"no-store"
    body = next(m["body"] for m in shed if m["type"] == "http.response.body")
    assert body == BODY and "surchargé" in json.loads(body)["detail"]
    assert mw.in_flight == 0 and mw.shed == 1


def test_health_the_live_stream_and_websockets_are_never_limited():
    async def go():
        gate = asyncio.Event()
        mw = ConcurrencyLimit(toy_app(gate), limit=1)
        busy = asyncio.create_task(call(mw))
        await asyncio.sleep(0.02)
        assert status_of(await call(mw)) == 503                                     # la limite s'applique bien
        gate.set()
        results = {}
        gate2 = asyncio.Event(); gate2.set()
        mw2 = ConcurrencyLimit(toy_app(gate), limit=1)
        # saturer mw2 avec une requête normale, puis vérifier les exemptions
        gate3 = asyncio.Event()
        mw3 = ConcurrencyLimit(toy_app(gate3), limit=1)
        pending = asyncio.create_task(call(mw3))
        await asyncio.sleep(0.02)
        gate3.set()                                                                 # les exemptions n'attendent pas : la porte est ouverte, mais elles doivent passer MÊME saturé
        gate4 = asyncio.Event(); mw4 = ConcurrencyLimit(toy_app(gate4), limit=1)
        hold = asyncio.create_task(call(mw4, "/api/x"))
        await asyncio.sleep(0.02)
        gate4.set()
        return await busy, await pending, await hold, mw2, mw4
    run(go())

    async def exempt_case():
        gate = asyncio.Event()
        mw = ConcurrencyLimit(toy_app(gate), limit=1)
        hold = asyncio.create_task(call(mw, "/api/x"))
        await asyncio.sleep(0.02)
        out = {}
        for path in ("/api/health", "/api/connections/1/events", "/api/connections/7/events"):
            sent_task = asyncio.create_task(call(mw, path))
            await asyncio.sleep(0.02)
            out[path] = sent_task.done()                                            # a-t-elle commencé sans attendre la place ? (elle attend la porte, mais n'a pas été REFUSÉE)
        saturated = await call(mw, "/api/other")
        ws = await call(mw, "/api/console/x", scope_type="websocket")
        gate.set()
        await hold
        return out, status_of(saturated), ws
    out, saturated, ws = run(exempt_case())
    assert saturated == 503 and ws[0]["type"] == "websocket.close"                  # un WebSocket passe même saturé
    assert not any(out.values())                                                    # exemptées : aucune n'a été refusée (elles attendent seulement la porte du faux service)


def test_exempt_paths_are_exactly_health_and_the_events_stream():
    assert ConcurrencyLimit.exempt("/api/health") and ConcurrencyLimit.exempt("/api/connections/3/events")
    for path in ("/api/healthz", "/api/health/x", "/api/events-list", "/api/connections", "/api/audit", "/api/auth/login"):
        assert not ConcurrencyLimit.exempt(path), path


def test_the_counter_never_leaks_on_errors_or_cancellation():
    async def go():
        mw = ConcurrencyLimit(toy_app(asyncio.Event(), boom=True), limit=2)
        for _ in range(5):
            with pytest.raises(RuntimeError):
                await call(mw)
        assert mw.in_flight == 0                                                    # une exception ne bloque pas la place
        gate = asyncio.Event()
        mw2 = ConcurrencyLimit(toy_app(gate), limit=2)
        tasks = [asyncio.create_task(call(mw2)) for _ in range(2)]
        await asyncio.sleep(0.02)
        assert mw2.in_flight == 2
        for t in tasks:
            t.cancel()                                                              # un client qui part en cours de route
        await asyncio.gather(*tasks, return_exceptions=True)
        return mw2.in_flight
    assert run(go()) == 0


def test_limit_zero_means_unlimited_and_none_reads_the_setting(monkeypatch):
    async def go(limit):
        gate = asyncio.Event()
        mw = ConcurrencyLimit(toy_app(gate), limit=limit)
        tasks = [asyncio.create_task(call(mw)) for _ in range(30)]
        await asyncio.sleep(0.05)
        gate.set()
        return [status_of(r) for r in await asyncio.gather(*tasks)]
    assert run(go(0)) == [200] * 30
    monkeypatch.setattr(get_settings(), "kaji_max_concurrent_requests", 4)
    codes = run(go(None))                                                   # None : lit le réglage, à chaque requête
    assert codes.count(200) == 4 and codes.count(503) == 26


def test_the_default_limit_leaves_room_under_the_database_pool():
    default = Settings(_env_file=None, kaji_secret_key="x" * 40).kaji_max_concurrent_requests
    assert 0 < default <= DB_POOL_SIZE + DB_POOL_OVERFLOW - 20                      # sinon la limite ne protège de rien : le pool se saturerait avant


def test_shedding_is_logged_but_not_more_than_every_ten_seconds(caplog):
    async def go():
        gate = asyncio.Event()
        mw = ConcurrencyLimit(toy_app(gate), limit=1)
        hold = asyncio.create_task(call(mw))
        await asyncio.sleep(0.02)
        for _ in range(25):
            await call(mw)
        gate.set()
        await hold
    with caplog.at_level(logging.WARNING, logger="kaji.limits"):
        run(go())
    messages = [r.getMessage() for r in caplog.records if r.name == "kaji.limits"]
    assert len(messages) == 1 and "surcharge" in messages[0] and "limite 1" in messages[0]


def test_in_the_real_app_a_saturated_server_sheds_load_and_still_answers_health_and_the_session(client, tmp_path, monkeypatch):
    import app.db as db_module
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL
    from sqlalchemy.orm import sessionmaker

    from app.db import engine_kwargs
    from app.migrations import run_migrations
    url = URL.create("sqlite", database=str(tmp_path / "kaji.db"))
    engine = create_engine(url, **engine_kwargs(str(url)))
    run_migrations(engine)
    monkeypatch.setattr(db_module, "_engine", engine)
    monkeypatch.setattr(db_module, "_SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setattr(get_settings(), "kaji_max_concurrent_requests", 5)

    async def slow(request):
        await asyncio.sleep(0.4)
        return httpx.Response(200, json={"data": [{"node": "n1", "status": "online"}]})
    app.dependency_overrides[get_base_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(slow)))
    try:
        client.post("/api/auth/setup", json={"username": "alice", "password": PWD})
        client.post("/api/connections", json={"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": "s3cret-1234"})

        async def go():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://kaji.test") as c:
                await c.post("/api/auth/login", json={"username": "alice", "password": PWD})
                await c.get("/api/health")                                         # échauffement : la toute première requête d'une application coûte ~0,4 s (démarrage à froid, mesuré)
                tasks = [asyncio.create_task(c.get("/api/connections/1/nodes")) for _ in range(20)]
                await asyncio.sleep(0.15)
                t0 = time.perf_counter()
                health = await c.get("/api/health")
                elapsed = time.perf_counter() - t0
                rs = await asyncio.gather(*tasks)
                late = await c.get("/api/connections/1/nodes")                      # la place est revenue
                return [r.status_code for r in rs], health.status_code, elapsed, late.status_code
        codes, health, elapsed, late = run(go())
    finally:
        app.dependency_overrides.pop(get_base_client_factory, None)
        engine.dispose()
    assert codes.count(200) <= 5 and codes.count(503) >= 15 and set(codes) <= {200, 503}      # pas de 500, pas de blocage : on accepte ce qu'on peut servir, on refuse le reste
    assert health == 200 and elapsed < 0.2 and late == 200
