import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
UPID = "UPID:enzo:0001A2B3:00C4D5E6:67890ABC:vzsnapshot:105:kaji@pve!kaji:"
CALLS: list[tuple[str, str, str]] = []
FAIL: dict = {}


def _handler(request: httpx.Request) -> httpx.Response:
    CALLS.append((request.method, request.url.path.removeprefix("/api2/json"), request.content.decode() or str(request.url.query, "utf-8")))
    if FAIL.get("code"):
        return httpx.Response(FAIL["code"], json={"data": None})
    if request.method == "GET":
        return httpx.Response(200, json={"data": [
            {"name": "avant-maj", "snaptime": 200, "description": "avant mise à jour", "parent": "base"},
            {"name": "base", "snaptime": 100, "vmstate": 1},
            {"name": "current", "parent": "avant-maj", "description": "You are here!"},
        ]})
    return httpx.Response(200, json={"data": UPID})


@pytest.fixture
def api(client):
    CALLS.clear(); FAIL.clear()
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def u(cid, suffix="", gtype="lxc", vmid=105):
    return f"/api/connections/{cid}/guests/enzo/{gtype}/{vmid}/snapshots{suffix}"


def test_requires_auth(client):
    assert client.get(u(1)).status_code == 401
    assert client.post(u(1), json={"name": "abc"}).status_code == 401
    assert client.delete(u(1, "/abc?confirm=true")).status_code == 401
    assert client.post(u(1, "/abc/rollback"), json={"confirm": True}).status_code == 401


def test_list_hides_current_and_orders_by_time(api):
    c, cid = api
    r = c.get(u(cid)).json()
    assert [s["name"] for s in r["snapshots"]] == ["base", "avant-maj"]
    assert r["current_parent"] == "avant-maj" and r["snapshots"][0]["vmstate"] is True


def test_create_goes_through_the_snapshots_route_not_the_generic_action_route(api):
    c, cid = api
    r = c.post(u(cid), json={"name": "kaji-test", "description": " test "})
    assert r.status_code == 202 and r.json() == {"upid": UPID, "node": "enzo"}
    assert CALLS[0][:2] == ("POST", "/nodes/enzo/lxc/105/snapshot")
    assert "snapname=kaji-test" in CALLS[0][2] and "description=test" in CALLS[0][2]


def test_vmstate_only_for_vms(api):
    c, cid = api
    assert c.post(u(cid), json={"name": "kaji-test", "vmstate": True}).status_code == 422 and CALLS == []
    assert c.post(u(cid, gtype="qemu", vmid=108), json={"name": "kaji-test", "vmstate": True}).status_code == 202
    assert "vmstate=1" in CALLS[0][2]


@pytest.mark.parametrize("name", ["1abc", "a", "ab cd", "../etc", "a;b", "x" * 41, "é-snap", ""])
def test_invalid_names_rejected_without_calling_proxmox(api, name):
    c, cid = api
    assert c.post(u(cid), json={"name": name}).status_code == 422 and CALLS == []


def test_delete_requires_confirmation(api):
    c, cid = api
    assert c.delete(u(cid, "/kaji-test")).status_code == 400 and CALLS == []
    assert c.delete(u(cid, "/kaji-test?confirm=true")).status_code == 202
    assert CALLS == [("DELETE", "/nodes/enzo/lxc/105/snapshot/kaji-test", "")]


def test_delete_invalid_name_rejected(api):
    c, cid = api
    assert c.delete(u(cid, "/a b?confirm=true")).status_code in (404, 422) and CALLS == []


def test_rollback_requires_confirmation(api):
    c, cid = api
    assert c.post(u(cid, "/base/rollback"), json={}).status_code == 400
    assert c.post(u(cid, "/base/rollback"), json={"confirm": False}).status_code == 400 and CALLS == []
    assert c.post(u(cid, "/base/rollback"), json={"confirm": True}).status_code == 202
    assert CALLS[0][:2] == ("POST", "/nodes/enzo/lxc/105/snapshot/base/rollback")


def test_audit_covers_success_refusal_and_proxmox_errors_without_secrets(api):
    c, cid = api
    c.post(u(cid), json={"name": "kaji-test"})
    c.delete(u(cid, "/kaji-test"))                       # refusé : pas de confirmation
    c.post(u(cid, "/base/rollback"), json={"confirm": True})
    FAIL["code"] = 403
    assert c.delete(u(cid, "/kaji-test?confirm=true")).status_code == 502
    log = c.get("/api/audit").json()[::-1]
    assert [(e["action"], e["status"]) for e in log] == [
        ("snapshot-create", "started"), ("snapshot-delete", "error"), ("snapshot-rollback", "started"), ("snapshot-delete", "error")]
    assert log[0]["upid"] == UPID and log[2]["target"] == "lxc/105@enzo:base"
    assert SECRET not in c.get("/api/audit").text
