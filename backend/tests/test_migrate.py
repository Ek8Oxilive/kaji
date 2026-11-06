from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient
from app.routers.migrate import MigrateBody, shape_preflight

# ---------- vérifications préalables ----------

RAW = {"running": 0, "allowed_nodes": ["enzo2", "enzo"], "not_allowed_nodes": {"enzo3": {"unavailable_storages": ["nfs"]}},
       "local_disks": [{"volid": "local-lvm:vm-115-disk-0", "size": 1073741824}, {"volid": "local:iso/x.iso", "cdrom": 1}],
       "local_resources": ["pci:0000:01:00"]}


def test_preflight_excludes_source_cdrom_and_explains_blockers():
    p = shape_preflight(RAW, "enzo", ["enzo", "enzo2"])
    assert p["preflight"] is True and p["allowed_nodes"] == ["enzo2"]
    assert p["not_allowed"] == [{"node": "enzo3", "reasons": ["stockage indisponible : nfs"]}]
    assert [d["volid"] for d in p["local_disks"]] == ["local-lvm:vm-115-disk-0"] and p["local_resources"] == ["pci:0000:01:00"]


def test_node_both_allowed_and_refused_without_reason_is_kept_as_allowed():
    p = shape_preflight({"allowed_nodes": ["enzo", "enzo2"], "not_allowed_nodes": {"enzo2": {"unavailable_storages": []}}}, "enzo", ["enzo", "enzo2"])
    assert p["allowed_nodes"] == ["enzo2"] and p["not_allowed"] == []


def test_node_refused_with_a_reason_is_never_offered():
    raw = {"allowed_nodes": ["enzo", "enzo2"], "not_allowed_nodes": {"enzo2": {"unavailable_storages": ["nfs"]}}}
    p = shape_preflight(raw, "enzo", ["enzo", "enzo2"])
    assert p["allowed_nodes"] == [] and p["not_allowed"] == [{"node": "enzo2", "reasons": ["stockage indisponible : nfs"]}]


@pytest.mark.parametrize("raw", [None, {}, [], {"running": 1}])
def test_preflight_falls_back_to_online_nodes(raw):
    p = shape_preflight(raw, "enzo", ["enzo", "enzo2", "enzo3"])
    assert p["preflight"] is False and p["allowed_nodes"] == ["enzo2", "enzo3"] and p["local_disks"] == []


@pytest.mark.parametrize("bad", [{"target_node": "a;b"}, {"target_node": "-x"}, {"target_node": "a b"}, {"target_storage": "a;b"}, {"target_storage": "../x"}])
def test_invalid_bodies_rejected(bad):
    with pytest.raises(ValidationError):
        MigrateBody(**{"target_node": "enzo2", **bad})


# ---------- API ----------

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
UPID = "UPID:enzo:0001A2B3:00C4D5E6:67890ABC:qmigrate:115:kaji@pve!kaji:"
STATE = {"status": "stopped", "preflight": RAW}
CALLS: list = []
FAIL: dict = {}


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    CALLS.append((request.method, p, {k: v[0] for k, v in parse_qs(request.content.decode()).items()}))
    if FAIL.get("code") and request.method == "POST":
        return httpx.Response(FAIL["code"], json={"data": None})
    if p.endswith("/status/current"):
        return httpx.Response(200, json={"data": {"status": STATE["status"]}})
    if p == "/nodes":
        return httpx.Response(200, json={"data": [{"node": "enzo", "status": "online"}, {"node": "enzo2", "status": "online"}, {"node": "off", "status": "offline"}]})
    if p.endswith("/migrate") and request.method == "GET":
        return httpx.Response(200 if STATE["preflight"] is not None else 501, json={"data": STATE["preflight"]})
    return httpx.Response(200, json={"data": UPID})


@pytest.fixture
def api(client):
    CALLS.clear(); FAIL.clear(); STATE.update(status="stopped", preflight=RAW)
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def u(cid, gtype="qemu", vmid=115):
    return f"/api/connections/{cid}/guests/enzo/{gtype}/{vmid}/migrate"


def posts():
    return [x for x in CALLS if x[0] == "POST"]


def test_requires_auth(client):
    assert client.get(u(1)).status_code == 401
    assert client.post(u(1), json={"target_node": "enzo2"}).status_code == 401


def test_preflight_route(api):
    c, cid = api
    r = c.get(u(cid)).json()
    assert r["allowed_nodes"] == ["enzo2"] and r["preflight"] is True


def test_preflight_route_falls_back_when_proxmox_has_no_preflight(api):
    c, cid = api
    STATE["preflight"] = None
    r = c.get(u(cid)).json()
    assert r["preflight"] is False and r["allowed_nodes"] == ["enzo2"]          # le nœud hors ligne est exclu


def test_offline_migration_of_stopped_vm(api):
    c, cid = api
    r = c.post(u(cid), json={"target_node": "enzo2"})
    assert r.status_code == 202 and r.json() == {"upid": UPID, "node": "enzo", "target_node": "enzo2"}
    assert posts() == [("POST", "/nodes/enzo/qemu/115/migrate", {"target": "enzo2"})]


def test_same_node_refused_without_any_call(api):
    c, cid = api
    assert c.post(u(cid), json={"target_node": "enzo"}).status_code == 422 and CALLS == []


def test_running_machine_needs_confirmation(api):
    c, cid = api
    STATE["status"] = "running"
    r = c.post(u(cid), json={"target_node": "enzo2", "online": True})
    assert r.status_code == 400 and posts() == []
    assert c.post(u(cid), json={"target_node": "enzo2"}, ).status_code == 400 and posts() == []


def test_running_vm_must_migrate_online(api):
    c, cid = api
    STATE["status"] = "running"
    assert c.post(u(cid), json={"target_node": "enzo2", "confirm": True}).status_code == 422 and posts() == []
    r = c.post(u(cid), json={"target_node": "enzo2", "confirm": True, "online": True, "with_local_disks": True, "target_storage": "local-lvm"})
    assert r.status_code == 202
    assert posts()[0][2] == {"target": "enzo2", "online": "1", "with-local-disks": "1", "targetstorage": "local-lvm"}


def test_running_lxc_restarts(api):
    c, cid = api
    STATE["status"] = "running"
    r = c.post(u(cid, "lxc", 105), json={"target_node": "enzo2", "confirm": True})
    assert r.status_code == 202 and posts()[0][2] == {"target": "enzo2", "restart": "1"}


def test_vm_only_options_refused_for_lxc(api):
    c, cid = api
    assert c.post(u(cid, "lxc", 105), json={"target_node": "enzo2", "target_storage": "local-lvm"}).status_code == 422
    assert c.post(u(cid, "lxc", 105), json={"target_node": "enzo2", "with_local_disks": True}).status_code == 422 and posts() == []


def test_offline_options_not_sent_for_stopped_machine(api):
    c, cid = api
    c.post(u(cid), json={"target_node": "enzo2", "online": True, "with_local_disks": True})
    assert posts()[0][2] == {"target": "enzo2"}                  # arrêtée : ni online ni with-local-disks


def test_audit_trail_without_secrets(api):
    c, cid = api
    c.post(u(cid), json={"target_node": "enzo"})                 # refusé
    c.post(u(cid), json={"target_node": "enzo2"})
    FAIL["code"] = 403
    assert c.post(u(cid), json={"target_node": "enzo2"}).status_code == 502
    log = c.get("/api/audit").json()[::-1]
    assert [(e["action"], e["status"]) for e in log] == [("migrate", "error"), ("migrate", "started"), ("migrate", "error")]
    assert "-> enzo2" in log[1]["detail"] and log[1]["upid"] == UPID and SECRET not in c.get("/api/audit").text
