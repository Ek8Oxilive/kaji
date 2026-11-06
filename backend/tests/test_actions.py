import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
UPID = "UPID:enzo:0001A2B3:00C4D5E6:67890ABC:vzstart:105:kaji@pve!kaji:"
CALLS = []
FAIL = {}


def _handler(request: httpx.Request) -> httpx.Response:
    CALLS.append((request.method, request.url.path))
    if FAIL.get("code"):
        return httpx.Response(FAIL["code"], json={"data": None})
    path = request.url.path
    if request.method == "POST" and "/status/" in path:
        return httpx.Response(200, json={"data": UPID})
    if path.endswith("/status"):
        return httpx.Response(200, json={"data": {"status": "stopped", "exitstatus": "OK", "type": "vzstart",
                                                  "id": "105", "user": "kaji@pve!kaji", "starttime": 1}})
    if path.endswith("/log"):
        return httpx.Response(200, json={"data": [{"n": 1, "t": "starting"}, {"n": 2, "t": "TASK OK"}]})
    return httpx.Response(404, json={"data": None})


@pytest.fixture
def api(client):
    CALLS.clear()
    FAIL.clear()
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler))
    )
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def url(cid, action, node="enzo", gtype="lxc", vmid=105):
    return f"/api/connections/{cid}/guests/{node}/{gtype}/{vmid}/{action}"


def test_requires_auth(client):
    assert client.post("/api/connections/1/guests/enzo/lxc/105/start").status_code == 401
    assert client.get("/api/audit").status_code == 401


@pytest.mark.parametrize("action", ["start", "shutdown", "reboot"])
def test_safe_actions_call_proxmox_and_return_upid(api, action):
    c, cid = api
    r = c.post(url(cid, action))
    assert r.status_code == 202 and r.json()["upid"] == UPID
    assert CALLS == [("POST", f"/api2/json/nodes/enzo/lxc/105/status/{action}")]


def test_stop_requires_confirmation(api):
    c, cid = api
    r = c.post(url(cid, "stop"))
    assert r.status_code == 400 and CALLS == []
    r = c.post(url(cid, "stop"), json={"confirm": False})
    assert r.status_code == 400 and CALLS == []
    r = c.post(url(cid, "stop"), json={"confirm": True})
    assert r.status_code == 202 and CALLS == [("POST", "/api2/json/nodes/enzo/lxc/105/status/stop")]


@pytest.mark.parametrize("kw", [
    {"action": "delete"}, {"action": "start", "gtype": "ct"}, {"action": "start", "vmid": 5},
    {"action": "start", "node": "a;b"}, {"action": "start", "node": "-x"},
])
def test_invalid_targets_rejected_without_calling_proxmox(api, kw):
    c, cid = api
    assert c.post(url(cid, **kw)).status_code == 422
    assert CALLS == []


def test_unknown_connection(api):
    assert api[0].post(url(999, "start")).status_code == 404


def test_proxmox_refusal_is_reported_and_audited(api):
    c, cid = api
    FAIL["code"] = 403
    r = c.post(url(cid, "start"))
    assert r.status_code == 502 and "Droits insuffisants" in r.json()["detail"]
    entry = c.get("/api/audit").json()[0]
    assert entry["status"] == "error" and entry["action"] == "start" and entry["upid"] is None


def test_audit_records_success_confirm_missing_and_never_secrets(api):
    c, cid = api
    c.post(url(cid, "start"))
    c.post(url(cid, "stop"))                              # refusé : pas de confirmation
    c.post(url(cid, "stop"), json={"confirm": True})
    log = c.get("/api/audit").json()
    assert [(e["action"], e["status"]) for e in log] == [("stop", "started"), ("stop", "error"), ("start", "started")]
    assert log[0]["user"] == "admin" and log[0]["target"] == "lxc/105@enzo" and log[0]["upid"] == UPID
    assert SECRET not in c.get("/api/audit").text


def test_task_status_and_log(api):
    c, cid = api
    r = c.get(f"/api/connections/{cid}/tasks/enzo/{UPID}").json()
    assert r["ok"] is True and r["exitstatus"] == "OK" and r["status"] == "stopped"
    log = c.get(f"/api/connections/{cid}/tasks/enzo/{UPID}/log").json()
    assert log[-1]["t"] == "TASK OK"


@pytest.mark.parametrize("bad", ["UPID:x", "pas-un-upid", "UPID:enzo:1:2:3:t:i:u/..:"])
def test_invalid_upid_rejected(api, bad):
    c, cid = api
    assert c.get(f"/api/connections/{cid}/tasks/enzo/{bad}").status_code in (404, 422)
    assert CALLS == []
