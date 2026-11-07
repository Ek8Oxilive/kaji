import httpx
import pytest

from app import servicespec as SP
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
UPID = "UPID:enzo:0001A2B3:00C4D5E6:67890ABC:srvrestart:chrony:kaji@pve!kaji:"
CALLS: list[tuple[str, str]] = []
FAIL: dict = {}


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    CALLS.append((request.method, p))
    if FAIL.get("code"):
        return httpx.Response(FAIL["code"], json={"data": None, "message": f"détail interne {SECRET}"})
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


def u(cid, service, action, node="enzo"):
    return f"/api/connections/{cid}/nodes/{node}/services/{service}/{action}"


def test_restart_normal_service(api):
    c, cid = api
    r = c.post(u(cid, "chrony", "restart"), json={"confirm": True})
    assert r.status_code == 202 and r.json() == {"upid": UPID, "node": "enzo"}
    assert CALLS == [("POST", "/nodes/enzo/services/chrony/restart")]


def test_start_needs_no_confirmation_but_others_do(api):
    c, cid = api
    assert c.post(u(cid, "chrony", "start"), json={}).status_code == 202
    for action in ("stop", "restart", "reload"):
        assert c.post(u(cid, "chrony", action), json={}).status_code == 400
    assert len(CALLS) == 1


@pytest.mark.parametrize("service", sorted(SP.NO_STOP))
def test_never_stops_vital_or_access_services(api, service):
    c, cid = api
    r = c.post(u(cid, service, "stop"), json={"confirm": True, "type_name": service})
    assert r.status_code == 422 and not CALLS


def test_cluster_services_need_their_name_retyped(api):
    c, cid = api
    for service in ("corosync", "pve-cluster"):
        assert c.post(u(cid, service, "restart"), json={"confirm": True}).status_code == 400
        assert c.post(u(cid, service, "restart"), json={"confirm": True, "type_name": "autre"}).status_code == 400
    assert not CALLS
    assert c.post(u(cid, "corosync", "restart"), json={"confirm": True, "type_name": "corosync"}).status_code == 202
    assert CALLS == [("POST", "/nodes/enzo/services/corosync/restart")]


def test_sensitive_service_restart_allowed_with_confirm(api):
    c, cid = api
    assert c.post(u(cid, "pveproxy", "restart"), json={"confirm": True}).status_code == 202


def test_unknown_service_is_refused_without_calling_proxmox(api):
    c, cid = api
    for s in ("nginx", "syslog", "ssh", "pveproxy2"):
        assert c.post(u(cid, s, "restart"), json={"confirm": True}).status_code == 404
    assert not CALLS


@pytest.mark.parametrize("service", ["a;b", "-x", "A", "a.b", "x" * 60, "chrony;x", "x;chrony"])
def test_service_name_is_validated(api, service):
    """422 (motif ancré), pas seulement 404 de la liste blanche : deux garde-fous distincts."""
    c, cid = api
    assert c.post(u(cid, service, "restart"), json={"confirm": True}).status_code == 422
    assert not CALLS


def test_encoded_slash_in_service_name(api):
    c, cid = api
    assert c.post(u(cid, "a%2Fb", "restart"), json={"confirm": True}).status_code in (404, 422)
    assert not CALLS


def test_unknown_action_and_node(api):
    c, cid = api
    assert c.post(u(cid, "chrony", "disable"), json={"confirm": True}).status_code == 422
    assert c.post(u(cid, "chrony", "restart", node="a;b"), json={"confirm": True}).status_code in (404, 422)
    assert not CALLS


def test_requires_login(api):
    c, cid = api
    c.post("/api/auth/logout")
    assert c.post(u(cid, "chrony", "restart"), json={"confirm": True}).status_code == 401
    assert not CALLS


def test_audit_success_refusal_error_without_secret(api):
    c, cid = api
    c.post(u(cid, "chrony", "restart"), json={"confirm": True})
    c.post(u(cid, "sshd", "stop"), json={"confirm": True})
    FAIL["code"] = 403
    assert c.post(u(cid, "cron", "restart"), json={"confirm": True}).status_code == 502
    log = c.get("/api/audit").json()[::-1]
    assert [(e["action"], e["status"]) for e in log] == [("service-restart", "started"), ("service-stop", "error"), ("service-restart", "error")]
    assert log[0]["upid"] == UPID and log[0]["target"] == "service/chrony@enzo"
    assert SECRET not in c.get("/api/audit").text


def test_proxmox_error_does_not_leak(api):
    c, cid = api
    FAIL["code"] = 500
    r = c.post(u(cid, "chrony", "restart"), json={"confirm": True})
    assert r.status_code == 502 and SECRET not in r.text and "interne" not in r.text


def test_risk_levels_are_exclusive_and_cover_known():
    assert not (SP.VITAL & SP.SENSITIVE) and not (SP.VITAL & SP.NORMAL) and not (SP.SENSITIVE & SP.NORMAL)
    assert SP.NO_STOP <= SP.KNOWN
    assert SP.risk("corosync") == "vital" and SP.risk("pveproxy") == "sensitive" and SP.risk("chrony") == "normal"
