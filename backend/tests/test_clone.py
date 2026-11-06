from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient
from app.routers.clone import CloneBody, clone_params

# ---------- paramètres ----------

def test_full_clone_params_vm_and_lxc():
    p = clone_params(CloneBody(name="copie", pool="kaji-test", storage="local-lvm", target_node="enzo2", description=" d "), "qemu", 116)
    assert p == {"newid": 116, "name": "copie", "full": 1, "target": "enzo2", "storage": "local-lvm", "pool": "kaji-test", "description": "d"}
    l = clone_params(CloneBody(name="copie"), "lxc", 117)
    assert l == {"newid": 117, "hostname": "copie", "full": 1}


def test_linked_clone_and_storage_rules():
    assert clone_params(CloneBody(name="lie", full=False), "qemu", 120)["full"] == 0
    with pytest.raises(ValueError):
        clone_params(CloneBody(name="lie", full=False, storage="local-lvm"), "qemu", 120)   # stockage = clone complet seulement


@pytest.mark.parametrize("bad", [{"name": "-x"}, {"name": "a b"}, {"name": "a;b"}, {"name": ""}, {"name": "x" * 64},
                                 {"newid": 99}, {"target_node": "a;b"}, {"target_node": "-x"}, {"storage": "a;b"}, {"pool": "../x"},
                                 {"snapshot": "1abc"}, {"snapshot": "a b"}, {"description": "x" * 201}])
def test_invalid_bodies_rejected(bad):
    with pytest.raises(ValidationError):
        CloneBody(**{"name": "ok", **bad})


def test_unknown_fields_ignored():
    assert "args" not in clone_params(CloneBody(name="ok", **{"args": "-evil"}), "qemu", 116)


# ---------- API ----------

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
UPID = "UPID:enzo:0001A2B3:00C4D5E6:67890ABC:qmclone:115:kaji@pve!kaji:"
CALLS: list = []
FAIL: dict = {}


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    CALLS.append((request.method, p, {k: v[0] for k, v in parse_qs(request.content.decode()).items()}))
    if FAIL.get("code") and p != "/cluster/nextid":
        return httpx.Response(FAIL["code"], json={"data": None})
    return httpx.Response(200, json={"data": "116" if p == "/cluster/nextid" else UPID})


@pytest.fixture
def api(client):
    CALLS.clear(); FAIL.clear()
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def u(cid, gtype="qemu", vmid=115):
    return f"/api/connections/{cid}/guests/enzo/{gtype}/{vmid}/clone"


def test_requires_auth(client):
    assert client.post(u(1), json={"name": "x1"}).status_code == 401


def test_clone_goes_through_the_clone_route_with_nextid(api):
    c, cid = api
    r = c.post(u(cid), json={"name": "kaji-clone", "pool": "kaji-test"})
    assert r.status_code == 202 and r.json() == {"upid": UPID, "node": "enzo", "newid": 116, "target_node": "enzo"}
    assert [x[1] for x in CALLS] == ["/cluster/nextid", "/nodes/enzo/qemu/115/clone"]
    assert CALLS[1][2] == {"newid": "116", "name": "kaji-clone", "full": "1", "pool": "kaji-test"}


def test_clone_lxc_uses_hostname_and_explicit_id(api):
    c, cid = api
    c.post(u(cid, "lxc", 105), json={"name": "web2", "newid": 300, "target_node": "enzo2"})
    assert [x[1] for x in CALLS] == ["/nodes/enzo/lxc/105/clone"]
    assert CALLS[0][2] == {"newid": "300", "hostname": "web2", "full": "1", "target": "enzo2"}


def test_clone_onto_the_same_id_refused_without_calling_proxmox(api):
    c, cid = api
    assert c.post(u(cid), json={"name": "x1", "newid": 115}).status_code == 422
    assert not any(x[0] == "POST" for x in CALLS)


@pytest.mark.parametrize("payload", [{"name": "a b"}, {"name": "ok", "storage": "a;b"}, {"name": "ok", "full": False, "storage": "local-lvm"}])
def test_invalid_requests_rejected(api, payload):
    c, cid = api
    assert c.post(u(cid), json=payload).status_code == 422 and not any(x[0] == "POST" for x in CALLS)


def test_audit_success_and_refusal_without_secrets(api):
    c, cid = api
    c.post(u(cid), json={"name": "kaji-clone", "pool": "kaji-test"})
    FAIL["code"] = 403
    assert c.post(u(cid), json={"name": "autre"}).status_code == 502
    log = c.get("/api/audit").json()[::-1]
    assert [(e["action"], e["status"]) for e in log] == [("clone", "started"), ("clone", "error")]
    assert log[0]["target"] == "qemu/115@enzo" and "#116" in log[0]["detail"] and log[0]["upid"] == UPID
    assert SECRET not in c.get("/api/audit").text
