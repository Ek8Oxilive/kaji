"""Robustesse (jalon J3, ticket #457) : Proxmox lent, injoignable, qui répond n'importe quoi ; les pages qui n'en dépendent pas restent rapides ; les requêtes se font en parallèle.

Le premier jet de ces tests a trouvé un VRAI défaut : une réponse 200 qui n'est pas du JSON Proxmox (portail captif, proxy, mauvaise adresse) faisait planter la route par une exception
non gérée (erreur 500 brute) ; elle donne maintenant un 502 clair (`ProxmoxProtocolError`).
"""
import asyncio
import time

import httpx
import pytest

from app.db import Base, get_engine
from app.deps import get_base_client_factory
from app.live import Hub
from app.main import app
from app.proxmox import ProxmoxClient, ProxmoxProtocolError
from app.routers.live import make_fetch

PWD = "un-mot-de-passe-solide"
SECRET_IN_BODY = "SECRET-NE-DOIT-JAMAIS-ETRE-RECOPIE"
NODES = {"data": [{"node": "n1", "status": "online"}]}


class Pve:
    """Faux Proxmox dont le comportement se change en cours de route."""

    def __init__(self):
        self.mode, self.delay, self.calls = "ok", 0.0, 0

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        m = self.mode
        if m == "html":
            return httpx.Response(200, text=f"<html>Portail captif {SECRET_IN_BODY}</html>", headers={"content-type": "text/html"})
        if m == "empty":
            return httpx.Response(200, content=b"")
        if m == "list":
            return httpx.Response(200, json=[1, 2, 3])
        if m == "nodata":
            return httpx.Response(200, json={"oops": SECRET_IN_BODY})
        if m == "500":
            return httpx.Response(500, text=SECRET_IN_BODY)
        if m == "502":
            return httpx.Response(502, text=f"Bad Gateway {SECRET_IN_BODY}")
        if m == "401":
            return httpx.Response(401, json={"data": None})
        if m == "403":
            return httpx.Response(403, json={"data": None})
        if m == "connect":
            raise httpx.ConnectError("Connection refused")
        if m == "cert":
            raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
        if m == "timeout":
            raise httpx.ReadTimeout("trop lent")
        p = request.url.path
        if p.endswith("/cluster/resources"):
            return httpx.Response(200, json={"data": []})
        if p.endswith("/cluster/status"):
            return httpx.Response(200, json={"data": [{"type": "cluster", "name": "c", "quorate": 1}]})
        return httpx.Response(200, json=NODES)


@pytest.fixture
def pve():
    return Pve()


@pytest.fixture
def lab(client, pve, tmp_path, monkeypatch):
    """Une VRAIE base fichier (comme en production) : la base de test en mémoire n'a qu'une connexion partagée, qui ne supporte pas des requêtes simultanées de plusieurs threads."""
    import app.db as db_module
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL
    from sqlalchemy.orm import sessionmaker

    from app.migrations import run_migrations
    from app.db import engine_kwargs
    url = URL.create("sqlite", database=str(tmp_path / "kaji.db"))
    engine = create_engine(url, **engine_kwargs(str(url)))                                          # la VRAIE configuration de production (pool compris)
    run_migrations(engine)
    monkeypatch.setattr(db_module, "_engine", engine)
    monkeypatch.setattr(db_module, "_SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    app.dependency_overrides[get_base_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(pve.handler)))
    client.post("/api/auth/setup", json={"username": "alice", "password": PWD})
    client.post("/api/connections", json={"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": "s3cret-1234"})
    yield client
    app.dependency_overrides.pop(get_base_client_factory, None)
    engine.dispose()


ROUTES = ["/api/connections/1/nodes", "/api/connections/1/guests", "/api/connections/1/cluster/status", "/api/connections/1/storages"]


@pytest.mark.parametrize("mode,code,needle", [
    ("html", 502, "ce n'est pas l'API de Proxmox"), ("empty", 502, "ce n'est pas l'API de Proxmox"), ("list", 502, "ce n'est pas l'API de Proxmox"),
    ("nodata", 502, "ce n'est pas l'API de Proxmox"), ("500", 502, "Proxmox a répondu 500"), ("502", 502, "Proxmox a répondu 502"),
    ("401", 502, "Token refusé par Proxmox"), ("403", 502, "Droits insuffisants"), ("connect", 502, "Proxmox injoignable"),
    ("cert", 502, "certificat"), ("timeout", 504, "Proxmox ne répond pas"),
])
def test_every_way_proxmox_can_misbehave_gives_a_clear_gateway_error_never_a_500_nor_a_leak(lab, pve, mode, code, needle):
    pve.mode = mode
    for route in ROUTES:
        r = lab.get(route)
        assert r.status_code == code, (route, r.status_code, r.text)
        assert needle.lower() in r.json()["detail"].lower(), (route, r.text)
        assert SECRET_IN_BODY not in r.text and "Traceback" not in r.text                           # ni le corps de Proxmox ni une trace ne sont recopiés


def test_a_healthy_proxmox_still_works_after_every_failure(lab, pve):
    for mode in ("html", "500", "connect", "timeout", "nodata"):
        pve.mode = mode
        assert lab.get("/api/connections/1/nodes").status_code in (502, 504)
    pve.mode = "ok"
    assert lab.get("/api/connections/1/nodes").status_code == 200                                    # aucun état collant


@pytest.mark.parametrize("method", ["get", "get_envelope", "get_with_total", "post", "put", "delete"])
@pytest.mark.parametrize("body,kind", [(b"<html>x</html>", "html"), (b"", "vide"), (b'{"oops": 1}', "sans data"), (b"[1,2]", "liste")])
def test_every_client_method_raises_the_controlled_error_on_a_malformed_answer(method, body, kind):
    async def go():
        client = ProxmoxClient("h", "u@pve", "t", "s", transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body)))
        try:
            call = getattr(client, method)
            return await (call("/x") if method in ("get", "get_envelope", "get_with_total", "delete") else call("/x", a="1"))
        finally:
            await client.aclose()
    if method == "get_envelope" and kind in ("sans data", "liste"):
        assert asyncio.run(go()) is not None                                                         # l'enveloppe laisse passer un JSON valide : c'est l'appelant qui lit
        return
    with pytest.raises(ProxmoxProtocolError):
        asyncio.run(go())


def test_the_client_always_has_bounded_timeouts():
    client = ProxmoxClient("h", "u@pve", "t", "s")
    t = client._client.timeout
    assert t.connect == t.read == t.write == 15 and t.pool == 15


def _asgi_client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://kaji.test")


def test_pages_that_do_not_need_proxmox_stay_fast_while_proxmox_hangs(lab, pve):
    pve.delay = 1.0

    async def go():
        async with _asgi_client() as c:
            assert (await c.post("/api/auth/login", json={"username": "alice", "password": PWD})).status_code == 200
            await c.get("/api/health")                                                                      # échauffement : FastAPI construit tout son routage (~650 routes, ≈ 1 s) à la 1re requête du processus
            slow = [asyncio.create_task(c.get("/api/connections/1/nodes")) for _ in range(5)]          # cinq requêtes bloquées sur Proxmox
            await asyncio.sleep(0.1)
            timings = {}
            for path in ("/api/health", "/api/connections", "/api/audit", "/api/auth/me", "/api/me/proxmox-tokens"):
                t0 = time.perf_counter()
                r = await c.get(path)
                timings[path] = (r.status_code, time.perf_counter() - t0)
            await asyncio.gather(*slow)
            return timings
    timings = asyncio.run(go())
    for path, (code, elapsed) in timings.items():
        assert code == 200, path
        assert elapsed < 0.5, f"{path} a pris {elapsed:.2f}s pendant que Proxmox était bloqué"      # bien moins que le délai de 1 s de Proxmox


def test_requests_to_a_slow_proxmox_run_in_parallel_not_one_after_the_other(lab, pve):
    pve.delay = 0.3

    async def go():
        async with _asgi_client() as c:
            await c.post("/api/auth/login", json={"username": "alice", "password": PWD})
            t0 = time.perf_counter()
            rs = await asyncio.gather(*[c.get("/api/connections/1/nodes") for _ in range(20)])
            return [r.status_code for r in rs], time.perf_counter() - t0
    codes, elapsed = asyncio.run(go())
    assert codes == [200] * 20
    assert elapsed < 0.3 * 20 / 4, f"20 requêtes de 0,3 s ont pris {elapsed:.1f}s : elles se sont mises en file au lieu de s'exécuter ensemble"


def test_the_live_poller_survives_garbage_then_recovers_and_says_why(lab, pve):
    from sqlalchemy.orm import Session
    fetch = make_fetch(1, lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(pve.handler)))

    async def go():
        hub = Hub(interval=0.02, error_interval=0.02)
        events, agen = [], hub.subscribe(1, fetch)
        pve.mode = "html"

        async def consume():
            async for item in agen:
                events.append(item)
        task = asyncio.create_task(consume())
        await asyncio.sleep(0.15)
        pve.mode = "ok"
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await agen.aclose()
        return events
    events = asyncio.run(go())
    kinds = [k for k, _ in events]
    assert "error" in kinds and "snapshot" in kinds and kinds.index("error") < kinds.index("snapshot")           # l'erreur d'abord, puis la reprise toute seule
    message = next(v for k, v in events if k == "error")
    assert "ce n'est pas l'API de Proxmox" in message and SECRET_IN_BODY not in str(events)


def test_the_database_pool_is_sized_for_many_slow_requests_and_the_memory_database_is_untouched():
    from app.db import DB_POOL_OVERFLOW, DB_POOL_SIZE, engine_kwargs
    prod = engine_kwargs("sqlite:////data/kaji.db")
    assert prod["pool_size"] == DB_POOL_SIZE >= 50 and prod["max_overflow"] == DB_POOL_OVERFLOW >= 100 and prod["connect_args"] == {"check_same_thread": False}
    mem = engine_kwargs("sqlite://")
    assert "pool_size" not in mem and mem["poolclass"].__name__ == "StaticPool"                      # la base de test en mémoire ne change pas
    assert engine_kwargs("postgresql://x/y") == {}


def test_sixty_concurrent_slow_proxmox_requests_do_not_exhaust_the_database_pool(lab, pve):
    """Le défaut constaté : au-delà de 15 requêtes lentes simultanées, le pool par défaut se saturait (attente jusqu'à 30 s, y compris pour les pages sans Proxmox)."""
    pve.delay = 0.3

    async def go():
        async with _asgi_client() as c:
            await c.post("/api/auth/login", json={"username": "alice", "password": PWD})
            await c.get("/api/health")                                                                      # échauffement (voir plus haut)
            slow = [asyncio.create_task(c.get("/api/connections/1/nodes")) for _ in range(60)]
            await asyncio.sleep(0.1)
            t0 = time.perf_counter()
            health = await c.get("/api/health")
            me = await c.get("/api/auth/me")                                                          # a besoin de la base : doit passer pendant que 60 requêtes attendent Proxmox
            quick = time.perf_counter() - t0
            rs = await asyncio.gather(*slow)
            return [r.status_code for r in rs], quick, health.status_code, me.status_code
    t0 = time.perf_counter()
    codes, quick, health, me = asyncio.run(go())
    assert codes == [200] * 60 and health == 200 and me == 200
    assert quick < 3.0, f"/api/auth/me a pris {quick:.2f}s pendant que 60 requêtes attendaient Proxmox"          # le défaut d'avant : 30 s (attente du pool)
    assert time.perf_counter() - t0 < 5
