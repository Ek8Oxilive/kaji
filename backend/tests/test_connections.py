import httpx
import pytest
from sqlalchemy import text

from app.db import get_engine
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
BODY = {"name": "test", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji",
        "token_secret": "s3cr3t-token-value"}
SEEN = {}


def _handler(request: httpx.Request) -> httpx.Response:
    SEEN["auth"] = request.headers.get("authorization")
    if "bad" in SEEN["auth"]:
        return httpx.Response(401, json={"data": None})
    return httpx.Response(200, json={"data": {"version": "8.2.4", "release": "8.2"}})


@pytest.fixture
def api(client):
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler))
    )
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    yield client
    app.dependency_overrides.clear()


def test_requires_auth(client):
    assert client.get("/api/connections").status_code == 401
    assert client.post("/api/connections", json=BODY).status_code == 401


def test_create_never_returns_or_stores_plain_secret(api):
    r = api.post("/api/connections", json=BODY)
    assert r.status_code == 201
    assert "token_secret" not in r.text and "s3cr3t" not in r.text
    with get_engine().connect() as c:
        stored = c.execute(text("select token_secret_enc from connections")).scalar()
    assert stored and "s3cr3t" not in stored
    assert "s3cr3t" not in api.get("/api/connections").text


def test_duplicate_name_conflict(api):
    api.post("/api/connections", json=BODY)
    assert api.post("/api/connections", json=BODY).status_code == 409


@pytest.mark.parametrize("host", ["https://10.0.0.5", "10.0.0.5/api", "a b", "x;rm"])
def test_invalid_host_rejected(api, host):
    assert api.post("/api/connections", json={**BODY, "host": host}).status_code == 422


def test_user_must_not_include_token(api):
    assert api.post("/api/connections", json={**BODY, "user": "kaji@pve!kaji"}).status_code == 422


def test_update_and_delete(api):
    cid = api.post("/api/connections", json=BODY).json()["id"]
    r = api.patch(f"/api/connections/{cid}", json={"host": "10.0.0.9", "token_secret": "nouveau-secret"})
    assert r.status_code == 200 and r.json()["host"] == "10.0.0.9"
    api.post(f"/api/connections/{cid}/test")
    assert "nouveau-secret" in SEEN["auth"]
    assert api.delete(f"/api/connections/{cid}").status_code == 204
    assert api.get(f"/api/connections/{cid}").status_code == 404


def test_saved_connection_test_ok_uses_decrypted_token(api):
    cid = api.post("/api/connections", json=BODY).json()["id"]
    r = api.post(f"/api/connections/{cid}/test")
    assert r.json() == {"ok": True, "version": "8.2.4", "release": "8.2"}
    assert SEEN["auth"] == "PVEAPIToken=kaji@pve!kaji=s3cr3t-token-value"


def test_unsaved_test_reports_refused_token(api):
    r = api.post("/api/connections/test", json={**BODY, "token_secret": "bad-token"})
    assert r.json() == {"ok": False, "error": "Utilisateur ou token refusé"}
