import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
UPID = "UPID:enzo:0001A2B3:00C4D5E6:67890ABC:aptupdate::kaji@pve!kaji:"
CALLS: list[tuple[str, str, str]] = []
FAIL: dict = {}


def _handler(request: httpx.Request) -> httpx.Response:
    CALLS.append((request.method, request.url.path.removeprefix("/api2/json"), request.content.decode() + request.url.query.decode()))
    if FAIL.get("code"):
        return httpx.Response(FAIL["code"], json={"data": None, "message": SECRET})
    return httpx.Response(200, json={"data": UPID})


@pytest.fixture
def api(client):
    CALLS.clear()
    FAIL.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def test_refresh_sends_plain_update_without_parameters(api):
    c, cid = api
    r = c.post(f"/api/connections/{cid}/nodes/enzo/apt/update")
    assert r.status_code == 202 and r.json() == {"upid": UPID, "node": "enzo"}
    assert CALLS == [("POST", "/nodes/enzo/apt/update", "")]      # ni notify, ni quiet, ni corps


def test_body_cannot_add_parameters(api):
    c, cid = api
    c.post(f"/api/connections/{cid}/nodes/enzo/apt/update", json={"notify": 1, "quiet": 1, "command": "x"})
    assert CALLS[0][2] == ""


def test_no_upgrade_route_exists(api):
    c, cid = api
    for path in ("upgrade", "dist-upgrade", "install"):
        assert c.post(f"/api/connections/{cid}/nodes/enzo/apt/{path}").status_code in (404, 405)
    assert not CALLS


@pytest.mark.parametrize("node", ["a;b", "-x", "a.b", "x" * 70])
def test_node_validated(api, node):
    c, cid = api
    assert c.post(f"/api/connections/{cid}/nodes/{node}/apt/update").status_code == 422
    assert not CALLS


def test_requires_login(api):
    c, cid = api
    c.post("/api/auth/logout")
    assert c.post(f"/api/connections/{cid}/nodes/enzo/apt/update").status_code == 401
    assert not CALLS


def test_audit_and_no_secret(api):
    c, cid = api
    c.post(f"/api/connections/{cid}/nodes/enzo/apt/update")
    FAIL["code"] = 403
    r = c.post(f"/api/connections/{cid}/nodes/enzo/apt/update")
    assert r.status_code == 502 and SECRET not in r.text
    log = c.get("/api/audit").json()[::-1]
    assert [(e["action"], e["status"]) for e in log] == [("apt-refresh", "started"), ("apt-refresh", "error")]
    assert log[0]["upid"] == UPID and log[0]["target"] == "node/enzo" and SECRET not in c.get("/api/audit").text
