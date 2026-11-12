"""Arrêter une tâche en cours (lot #310) : faux Proxmox STRICT. Ce fichier ne prouve rien sur un vrai cluster.

Le faux n'accepte que `GET /nodes/{node}/tasks/{upid}/status` et `DELETE /nodes/{node}/tasks/{upid}` SANS paramètre ; tout autre appel répond 400.
"""
import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient
from app.taskstopspec import STOPPABLE, parse_upid, stop_refusal, vmids_of

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
CALLS: list[dict] = []
STATE: dict = {}


def upid(ttype="vzdump", tid="115", node="enzo", user="kaji@pve!kaji"):
    return f"UPID:{node}:001939C8:0565C63C:6AF5788F:{ttype}:{tid}:{user}:"


def _json(code, data=None):
    return httpx.Response(code, json={"data": data})


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    CALLS.append({"method": request.method, "path": p, "query": dict(request.url.params), "body": request.content.decode()})
    if STATE.get("fail") and STATE["fail"][0] == request.method:
        return _json(STATE["fail"][1])
    if request.method == "GET" and p.startswith("/nodes/enzo/tasks/") and p.endswith("/status"):
        return _json(400) if request.url.params else _json(200, STATE.get("status", {"status": "running", "type": "vzdump"}))
    if request.method == "DELETE" and p.startswith("/nodes/enzo/tasks/") and not p.endswith(("/status", "/log")):
        return _json(400) if request.url.params or request.content else _json(200)
    return _json(404)


@pytest.fixture
def api(client):
    CALLS.clear()
    STATE.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def stop(c, cid, u, confirm=True, node="enzo"):
    return c.delete(f"/api/connections/{cid}/tasks/{node}/{u}" + ("?confirm=true" if confirm else ""))


def writes():
    return [x for x in CALLS if x["method"] != "GET"]


def audit(c):
    return c.get("/api/audit").json()


# ------------------------------------------------------------------ règles pures

def test_parse_upid():
    assert parse_upid(upid("qmstart", "115")) == {"node": "enzo", "type": "qmstart", "id": "115", "user": "kaji@pve!kaji"}
    assert parse_upid(upid("download", "alpine-virt.iso"))["id"] == "alpine-virt.iso"
    for bad in ("", "UPID", "UPID:enzo:1:2:3:t:i:u", "UPID:enzo:1:2:3:t:i:u:x", "XPID:enzo:1:2:3:t:i:u:", "UPID::1:2:3:t:i:u:", "UPID:enzo:1:2:3::i:u:", None, 5):
        assert parse_upid(bad) is None


def test_stoppable_never_contains_consoles_or_dangerous_types():
    dangerous = {"vncproxy", "vncshell", "termproxy", "spiceproxy", "vncwebsocket", "srvstart", "srvstop", "srvrestart", "srvreload", "qmcreate", "vzcreate", "qmdestroy", "vzdestroy",
                 "qmstop", "vzstop", "imgdel", "qmsnapshot", "qmrollback", "qmdelsnapshot", "vzsnapshot", "qmtemplate", "vztemplate", "ceph", "cephcreateosd", "hastart", "hastop",
                 "reloadnetworkall", "startall", "stopall", "migrateall", "pvesh", "aptinstall", "acmenewcert", "csync"}
    assert not dangerous & set(STOPPABLE) and all(STOPPABLE.values()) and len(STOPPABLE) == 16


def test_vmids_of():
    assert vmids_of({"type": "qmstart", "id": "115"}) == {115}
    assert vmids_of({"type": "vzdump", "id": "115,116"}) == {115, 116}
    assert vmids_of({"type": "vzdump", "id": ""}) == set() and vmids_of({"type": "download", "id": "116"}) == set()
    assert vmids_of({"type": "qmigrate", "id": "1,x"}) == set() and vmids_of({"type": "qmigrate", "id": "1,,2"}) == set()


def test_stop_refusal_rules():
    ok = parse_upid(upid("vzdump", "115"))
    assert stop_refusal(ok, {105, 108, 116}) is None
    assert "protégée" in stop_refusal(parse_upid(upid("qmigrate", "116")), {116})
    assert "protégée" in stop_refusal(parse_upid(upid("vzdump", "115,116")), {116})
    assert stop_refusal(parse_upid(upid("vzdump", "")), {116}) is None
    assert "ne s'arrête pas" in stop_refusal(parse_upid(upid("vncproxy", "116")), set())
    assert stop_refusal(None, set()) == "Identifiant de tâche (UPID) invalide"


# ------------------------------------------------------------------ API

def test_requires_auth(client):
    assert client.delete(f"/api/connections/1/tasks/enzo/{upid()}?confirm=true").status_code == 401


def test_stops_a_running_allowed_task_with_exact_calls_and_audit(api):
    c, cid = api
    u = upid("vzdump", "115")
    r = stop(c, cid, u)
    assert r.status_code == 200 and r.json() == {"stopped": True, "upid": u, "node": "enzo", "type": "vzdump"}
    assert [(x["method"], x["path"], x["query"]) for x in CALLS] == [("GET", f"/nodes/enzo/tasks/{u}/status", {}), ("DELETE", f"/nodes/enzo/tasks/{u}", {})]
    last = audit(c)[0]
    assert (last["action"], last["status"], last["detail"]) == ("task-stop", "started", "Sauvegarde arrêtée") and last["target"].startswith("enzo/UPID:")


@pytest.mark.parametrize("ttype", sorted(STOPPABLE))
def test_every_listed_type_can_be_stopped(api, ttype):
    c, cid = api
    assert stop(c, cid, upid(ttype, "115" if ttype.startswith(("qm", "vz")) else "fichier.iso")).status_code == 200


def test_confirm_required_without_any_call(api):
    c, cid = api
    assert stop(c, cid, upid(), confirm=False).status_code == 400 and CALLS == []
    assert c.delete(f"/api/connections/{cid}/tasks/enzo/{upid()}?confirm=false").status_code == 400 and CALLS == []


@pytest.mark.parametrize("bad", ["pas-un-upid", "UPID:enzo:zz:1:2:vzdump:115:u:", upid() + "x", "UPID:enzo:1:2:3:vzdump:1 5:u:", "UPID:en zo:1:2:3:vzdump:1:u:"])
def test_invalid_upid_is_422_without_call(api, bad):
    c, cid = api
    r = stop(c, cid, bad)
    assert r.status_code == 422 and CALLS == [] and SECRET not in r.text
    assert (audit(c)[0]["action"], audit(c)[0]["status"]) == ("task-stop", "error")


def test_node_mismatch_is_422_without_call(api):
    c, cid = api
    assert stop(c, cid, upid(node="enzo2")).status_code == 422 and CALLS == []


@pytest.mark.parametrize("ttype", ["vncproxy", "vncshell", "termproxy", "spiceproxy", "srvreload", "qmcreate", "qmdestroy", "qmsnapshot", "imgdel", "qmstop", "startall", "ceph", "hastart"])
def test_type_outside_whitelist_is_409_without_call(api, ttype):
    c, cid = api
    r = stop(c, cid, upid(ttype, "115"))
    assert r.status_code == 409 and CALLS == []
    assert audit(c)[0]["detail"] == f"refusée ({ttype})"


@pytest.mark.parametrize("ttype,tid", [("qmigrate", "116"), ("vzdump", "115,116"), ("qmstart", "105"), ("vzstart", "108"), ("vzreboot", "116")])
def test_protected_machine_is_409_even_confirmed(api, monkeypatch, ttype, tid):
    c, cid = api
    monkeypatch.setattr("app.routers.task_stop.get_settings", lambda: type("S", (), {"protected_vmids": {105, 108, 116}})())
    assert stop(c, cid, upid(ttype, tid)).status_code == 409 and CALLS == []


def test_backup_of_all_machines_or_unprotected_is_allowed_with_protected_set(api, monkeypatch):
    c, cid = api
    monkeypatch.setattr("app.routers.task_stop.get_settings", lambda: type("S", (), {"protected_vmids": {116}})())
    assert stop(c, cid, upid("vzdump", "")).status_code == 200 and stop(c, cid, upid("vzdump", "115")).status_code == 200


@pytest.mark.parametrize("st", [{"status": "stopped", "exitstatus": "OK"}, {"status": "stopped"}, {}, {"status": "RUNNING"}])
def test_task_not_running_is_409_and_nothing_deleted(api, st):
    c, cid = api
    STATE["status"] = st
    assert stop(c, cid, upid()).status_code == 409 and writes() == []


@pytest.mark.parametrize("data", [None, ["running"], "running"])
def test_unreadable_status_is_502_and_nothing_deleted(api, data):
    c, cid = api
    STATE["status"] = data
    assert stop(c, cid, upid()).status_code == 502 and writes() == []


@pytest.mark.parametrize("method,code", [("GET", 500), ("DELETE", 403), ("DELETE", 500)])
def test_proxmox_error_is_translated_audited_without_leak(api, method, code):
    c, cid = api
    STATE["fail"] = (method, code)
    r = stop(c, cid, upid())
    assert r.status_code == 502 and SECRET not in r.text and "10.0.0.5" not in r.text
    assert (audit(c)[0]["action"], audit(c)[0]["status"]) == ("task-stop", "error") and SECRET not in c.get("/api/audit").text


def test_invalid_path_params(api):
    c, cid = api
    assert stop(c, cid, upid(), node="-bad").status_code == 422 and CALLS == []
    assert c.delete(f"/api/connections/{cid}/tasks/enzo/{'x' * 301}?confirm=true").status_code == 422 and CALLS == []


# ------------------------------------------------------------------ champ `stoppable` de l'état d'une tâche

def _status_handler(data):
    def h(request):
        p = request.url.path.removeprefix("/api2/json")
        return _json(200, data) if request.method == "GET" and p.endswith("/status") else _json(404)
    return h


@pytest.mark.parametrize("ttype,tid,status,expected", [
    ("vzdump", "115", "running", True), ("vzdump", "115", "stopped", False), ("vncproxy", "115", "running", False), ("qmigrate", "116", "running", False), ("download", "x.iso", "running", True)])
def test_task_status_exposes_stoppable(api, monkeypatch, ttype, tid, status, expected):
    c, cid = api
    monkeypatch.setattr("app.routers.actions.get_settings", lambda: type("S", (), {"protected_vmids": {116}})())
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_status_handler({"status": status, "type": ttype, "exitstatus": "OK"}))))
    r = c.get(f"/api/connections/{cid}/tasks/enzo/{upid(ttype, tid)}")
    assert r.status_code == 200 and r.json()["stoppable"] is expected
