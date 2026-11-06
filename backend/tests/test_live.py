import asyncio
import json

import httpx
import pytest

from app.deps import get_client_factory
from app.live import Hub, sse
from app.main import app
from app.proxmox import ProxmoxClient
from app.routers.live import make_fetch, stream

PWD = "un-mot-de-passe-solide"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": "s3cr3t-value-xyz"}


def run(coro):
    return asyncio.run(coro)


async def nxt(agen, timeout=1.0):
    return await asyncio.wait_for(agen.__anext__(), timeout)


def counting_fetch(values):
    calls = {"n": 0}

    async def fetch():
        v = values[min(calls["n"], len(values) - 1)]
        calls["n"] += 1
        if isinstance(v, Exception):
            raise v
        return v
    return fetch, calls


# ---------- hub ----------

def test_sse_format():
    assert sse("snapshot", {"a": "é"}) == 'event: snapshot\ndata: {"a":"é"}\n\n'


def test_one_poller_shared_by_two_subscribers():
    async def go():
        hub = Hub(interval=0.05)
        fetch, calls = counting_fetch([{"v": 1}])
        a, b = hub.subscribe(1, fetch), hub.subscribe(1, fetch)
        assert await nxt(a) == ("snapshot", {"v": 1}) and await nxt(b) == ("snapshot", {"v": 1})
        assert hub.active() == {1: 2}
        await a.aclose(); await b.aclose()
        return calls["n"]
    assert run(go()) <= 2          # un seul interrogateur, pas un par abonné


def test_unchanged_snapshot_not_resent_but_changes_are():
    async def go():
        hub = Hub(interval=0.02)
        fetch, _ = counting_fetch([{"v": 1}, {"v": 1}, {"v": 1}, {"v": 2}])
        a = hub.subscribe(1, fetch)
        first, second = await nxt(a), await nxt(a)
        await a.aclose()
        return first, second
    assert run(go()) == (("snapshot", {"v": 1}), ("snapshot", {"v": 2}))


def test_late_subscriber_gets_current_state_immediately():
    async def go():
        hub = Hub(interval=5)           # l'intervalle est long : la 2e réponse ne peut venir que du cache
        fetch, _ = counting_fetch([{"v": 7}])
        a = hub.subscribe(1, fetch)
        await nxt(a)
        b = hub.subscribe(1, fetch)
        got = await nxt(b, timeout=0.5)
        await a.aclose(); await b.aclose()
        return got
    assert run(go()) == ("snapshot", {"v": 7})


def test_error_reported_once_then_recovers():
    async def go():
        hub = Hub(interval=0.02, error_interval=0.02)
        fetch, _ = counting_fetch([RuntimeError("Proxmox injoignable")] * 3 + [{"ok": True}])
        a = hub.subscribe(1, fetch)
        items = [await nxt(a), await nxt(a)]
        await a.aclose()
        return items
    assert run(go()) == [("error", "Proxmox injoignable"), ("snapshot", {"ok": True})]


def test_poller_stops_when_last_subscriber_leaves():
    async def go():
        hub = Hub(interval=0.02)
        fetch, calls = counting_fetch([{"v": 1}])
        a = hub.subscribe(1, fetch)
        await nxt(a)
        await a.aclose()
        n = calls["n"]
        await asyncio.sleep(0.15)
        return hub.active(), calls["n"] - n
    active, extra_calls = run(go())
    assert active == {} and extra_calls <= 1


def test_stream_emits_retry_snapshot_and_heartbeat():
    async def go():
        hub = Hub(interval=5)
        fetch, _ = counting_fetch([{"v": 1}])
        s = stream(hub, 1, fetch, heartbeat=0.05)
        chunks = [await nxt(s), await nxt(s), await nxt(s)]
        await s.aclose()
        return chunks, hub.active()
    chunks, active = run(go())
    assert chunks[0] == "retry: 3000\n\n" and chunks[1].startswith("event: snapshot") and chunks[2] == ": ping\n\n"
    assert active == {}                           # fermeture propre : plus aucun abonné


# ---------- construction de l'instantané et route ----------

def _handler(request: httpx.Request) -> httpx.Response:
    data = {
        "/api2/json/cluster/status": [{"type": "cluster", "name": "lab", "quorate": 1}, {"type": "node", "name": "enzo", "online": 1, "ip": "1.1.1.1"}],
        "/api2/json/nodes": [{"node": "enzo", "status": "online", "cpu": 0.1}],
        "/api2/json/cluster/resources": [{"type": "lxc", "vmid": 105, "name": "WEB", "node": "enzo", "status": "running"}, {"type": "node"}],
    }[request.url.path]
    return httpx.Response(200, json={"data": data})


@pytest.fixture
def api(client):
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def test_snapshot_combines_status_nodes_and_guests(api):
    _, cid = api
    snap = run(make_fetch(cid, lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))())
    assert snap["status"]["name"] == "lab" and snap["nodes"][0]["node"] == "enzo"
    assert [g["vmid"] for g in snap["guests"]] == [105]
    assert "s3cr3t" not in json.dumps(snap)


def test_snapshot_error_is_readable_and_secret_free(api):
    _, cid = api
    refuse = httpx.MockTransport(lambda r: httpx.Response(401, json={"data": None}))
    with pytest.raises(Exception) as e:
        run(make_fetch(cid, lambda **kw: ProxmoxClient(**kw, transport=refuse))())
    assert "refusé" in str(e.value.detail) and "s3cr3t" not in str(e.value.detail)


def test_events_route_requires_auth_and_known_connection(client):
    assert client.get("/api/connections/1/events").status_code == 401
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    assert client.get("/api/connections/999/events").status_code == 404
