import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
B = "/api/connections/{}"
DATA: dict = {}


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    if request.method != "GET":
        return httpx.Response(405, json={"data": None, "message": "lecture seule"})
    if p in DATA:
        v = DATA[p]
        return httpx.Response(v[0], json=v[1]) if isinstance(v, tuple) else httpx.Response(200, json={"data": v})
    return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})


@pytest.fixture
def api(client):
    DATA.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def test_status_whitelist_and_junk(api):
    c, cid = api
    DATA["/cluster/ha/status/current"] = [
        {"type": "quorum", "node": "enzo", "id": "quorum", "status": "OK", "quorate": 1},
        {"type": "fencing", "id": "fencing", "armed-state": "standby", "status": "standby (CRM watchdog standby)", "node": "enzo"},
        {"type": "service", "sid": "vm:100", "node": "enzo", "state": "started", "request_state": "started", "max_relocate": 1, "max_restart": 1, "status": "vm:100 (enzo, started)", "evil": SECRET},
        {"type": "bogus", "id": "x"}, {"type": "service", "sid": "../etc", "node": "a b", "state": "nope"}, "junk", 5,
    ]
    r = c.get(B.format(cid) + "/ha/status")
    assert r.status_code == 200 and SECRET not in r.text
    rows = r.json()
    assert [x["type"] for x in rows] == ["quorum", "fencing", "service", "service"]
    assert rows[0]["quorate"] is True and rows[1]["armed_state"] == "standby"
    assert rows[2]["sid"] == "vm:100" and rows[2]["state"] == "started" and "evil" not in rows[2]
    assert rows[3]["sid"] is None and rows[3]["node"] is None and rows[3]["state"] is None


def test_resources_and_rules(api):
    c, cid = api
    DATA["/cluster/ha/resources"] = [{"sid": "vm:101", "type": "vm", "state": "started", "max_restart": 1, "max_relocate": 1, "failback": 1, "digest": "d" * 40}, {"sid": "ct:100", "state": "bogus"},
                                     {"sid": "vm:1"}, {"sid": "x"}]
    DATA["/cluster/ha/rules"] = [
        {"rule": "ha-r1", "type": "node-affinity", "resources": "vm:101,ct:100,bad", "nodes": "enzo:2,enzo2,bad node:x", "strict": 1},
        {"rule": "ha-r2", "type": "resource-affinity", "resources": "vm:101,vm:102", "affinity": "negative", "disable": 1, "comment": "x" * 900},
        {"rule": "bad rule", "type": "node-affinity"}, {"rule": "r3", "type": "unknown"}]
    res = c.get(B.format(cid) + "/ha/resources").json()
    assert [x["sid"] for x in res] == ["ct:100", "vm:101"] and res[0]["state"] is None and res[1]["failback"] is True
    rules = c.get(B.format(cid) + "/ha/rules").json()
    assert [x["rule"] for x in rules] == ["ha-r1", "ha-r2"]
    assert rules[0]["resources"] == ["vm:101", "ct:100"] and rules[0]["nodes"] == [{"node": "enzo", "priority": 2}, {"node": "enzo2", "priority": None}] and rules[0]["strict"] is True
    assert rules[1]["affinity"] == "negative" and rules[1]["disable"] is True and len(rules[1]["comment"]) == 500


def test_replication(api):
    c, cid = api
    DATA["/cluster/replication"] = [{"id": "100-0", "guest": 100, "type": "local", "source": "enzo", "target": "enzo2", "schedule": "*/15", "rate": 10.5, "disable": 0, "comment": "ok"},
                                    {"id": "bad", "type": "local"}, {"id": "100-1", "target": "a b", "type": "weird"}]
    DATA["/nodes/enzo/replication"] = [{"id": "100-0", "guest": 100, "target": "enzo2", "last_sync": 1700000000, "next_sync": 1700000900, "duration": 3.2, "fail_count": 2, "error": "boom\x00x"},
                                       {"id": "../x"}]
    DATA["/nodes/enzo/replication/100-0/log"] = [{"n": 1, "t": "start"}, {"n": 2, "t": "end\x07"}, {"n": 3}, "junk"]
    jobs = c.get(B.format(cid) + "/replication").json()
    assert [j["id"] for j in jobs] == ["100-0", "100-1"] and jobs[0]["rate"] == 10.5 and jobs[1]["target"] is None and jobs[1]["type"] is None
    st = c.get(B.format(cid) + "/nodes/enzo/replication").json()
    assert len(st) == 1 and st[0]["fail_count"] == 2 and st[0]["error"] == "boomx" and st[0]["duration"] == 3.2
    assert c.get(B.format(cid) + "/nodes/enzo/replication/100-0/log").json() == ["start", "end"]
    assert c.get(B.format(cid) + "/nodes/enzo/replication/bad/log").status_code == 422
    assert c.get(B.format(cid) + "/nodes/en zo/replication").status_code == 422
    assert c.get(B.format(cid) + "/nodes/enzo/replication/100-0/log?limit=0").status_code == 422


def test_proxmox_error_is_translated_without_secret(api):
    c, cid = api
    DATA["/cluster/ha/resources"] = (403, {"data": None, "message": SECRET})
    r = c.get(B.format(cid) + "/ha/resources")
    assert r.status_code == 502 and SECRET not in r.text


def test_requires_login(client):
    assert client.get("/api/connections/1/ha/status").status_code == 401


def test_job_ids_nodes_priorities_and_numbers_are_strict(api):
    c, cid = api
    DATA["/cluster/replication"] = [{"id": "012-0"}, {"id": "100-"}, {"id": "100-0 x"}, {"id": "100-1", "rate": "fast"}, {"id": "100-2", "rate": True}, {"id": "100-3", "duration": "x"}]
    jobs = c.get(B.format(cid) + "/replication").json()
    assert [j["id"] for j in jobs] == ["100-1", "100-2", "100-3"] and all(j["rate"] is None for j in jobs)
    DATA["/nodes/enzo/replication"] = [{"id": "100-3", "duration": "x"}, {"id": "100-4", "duration": False}]
    assert [s["duration"] for s in c.get(B.format(cid) + "/nodes/enzo/replication").json()] == [None, None]
    DATA["/cluster/ha/rules"] = [{"rule": "r1", "type": "node-affinity", "nodes": "enzo:x,enzo2:1,bad node:1,enzo3:"}]
    assert c.get(B.format(cid) + "/ha/rules").json()[0]["nodes"] == [{"node": "enzo2", "priority": 1}, {"node": "enzo3", "priority": None}]
    assert c.get(B.format(cid) + "/nodes/enzo/replication/100-0/log?limit=2001").status_code == 422
