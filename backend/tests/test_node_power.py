import httpx
import pytest

from app import powerspec as PS
from app.config import get_settings
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
CALLS: list[tuple[str, str, str]] = []
ST: dict = {}


def cluster(nodes, quorate=True):
    return [{"type": "cluster", "name": "c", "quorate": 1 if quorate else 0}] + [{"type": "node", "name": n, "online": 1 if on else 0, "ip": "1.1.1.1"} for n, on in nodes]


def guest(vmid, node="enzo", status="running", template=0):
    return {"type": "qemu", "vmid": vmid, "name": f"vm{vmid}", "node": node, "status": status, "template": template}


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    CALLS.append((request.method, p, request.content.decode()))
    if ST.get("down"):
        return httpx.Response(500, json={"data": None, "message": SECRET})
    if p == "/cluster/status":
        return httpx.Response(200, json={"data": ST["cluster"]})
    if p == "/cluster/resources":
        return httpx.Response(200, json={"data": ST["guests"]})
    if p.endswith("/status") and request.method == "POST":
        if ST.get("write_fail"):
            return httpx.Response(403, json={"data": None, "message": SECRET})
        return httpx.Response(200, json={"data": None})
    return httpx.Response(404, json={"data": None})


@pytest.fixture
def api(client):
    CALLS.clear()
    ST.clear()
    ST.update(cluster=cluster([("enzo", True), ("enzo2", True), ("enzo3", True)]), guests=[])
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def go(c, cid, node="enzo", **b):
    return c.post(f"/api/connections/{cid}/nodes/{node}/power", json={"action": "reboot", "confirm": True, "type_name": node, **b})


def writes():
    return [x for x in CALLS if x[0] == "POST"]


def test_reboot_sends_command_to_proxmox(api):
    c, cid = api
    r = go(c, cid)
    assert r.status_code == 202 and r.json() == {"node": "enzo", "action": "reboot"}
    assert writes() == [("POST", "/nodes/enzo/status", "command=reboot")]


def test_shutdown_command(api):
    c, cid = api
    assert go(c, cid, action="shutdown").status_code == 202
    assert writes()[0][2] == "command=shutdown"


def test_needs_confirm_and_exact_name(api):
    c, cid = api
    assert go(c, cid, confirm=False).status_code == 400
    for typed in (None, "", "enzo2", "ENZO", "enzo "):
        assert go(c, cid, type_name=typed).status_code == 400
    assert not writes()


def test_running_guests_need_explicit_acceptance(api):
    c, cid = api
    ST["guests"] = [guest(100), guest(101, status="stopped"), guest(102, node="enzo2"), guest(900, template=1)]
    r = go(c, cid)
    assert r.status_code == 409 and "1 machine" in r.json()["detail"] and not writes()
    assert go(c, cid, accept_guests=True).status_code == 202


@pytest.fixture
def protected_105(monkeypatch):
    monkeypatch.setenv("KAJI_PROTECTED_VMIDS", "105,108")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()                     # remet l'environnement avant de vider le cache, pour ne rien laisser aux autres tests
    get_settings.cache_clear()


def test_protected_guest_blocks_even_with_acceptances(api, protected_105):
    c, cid = api
    ST["guests"] = [guest(105)]
    r = go(c, cid, accept_guests=True, accept_quorum_loss=True)
    assert r.status_code == 422 and "105" in r.json()["detail"] and not writes()
    ST["guests"] = [guest(105, status="stopped")]                       # arrêtée : plus de blocage
    assert go(c, cid, accept_guests=True).status_code == 202


def test_quorum_loss_needs_explicit_acceptance(api):
    c, cid = api
    ST["cluster"] = cluster([("enzo", True), ("enzo2", True)])           # 2 nœuds : en retirer un casse le quorum
    r = go(c, cid)
    assert r.status_code == 409 and "quorum" in r.json()["detail"] and not writes()
    assert go(c, cid, accept_quorum_loss=True).status_code == 202


def test_quorum_kept_with_three_nodes_and_standalone(api):
    c, cid = api
    assert go(c, cid).status_code == 202                                  # 3 nœuds : 2 restent
    ST["cluster"] = [{"type": "node", "name": "enzo", "online": 1}]       # nœud seul, sans cluster
    assert go(c, cid).status_code == 202


def test_offline_or_unknown_node(api):
    c, cid = api
    ST["cluster"] = cluster([("enzo", False), ("enzo2", True), ("enzo3", True)])
    assert go(c, cid).status_code == 409
    assert go(c, cid, node="inconnu").status_code == 404
    assert not writes()


def test_unreadable_state_refuses(api):
    c, cid = api
    ST["down"] = True
    r = go(c, cid)
    assert r.status_code == 502 and SECRET not in r.text and not writes()


def test_inputs_validated(api):
    c, cid = api
    assert c.post(f"/api/connections/{cid}/nodes/enzo/power", json={"action": "poweroff", "confirm": True, "type_name": "enzo"}).status_code == 422
    assert go(c, cid, node="a;b").status_code in (404, 422)
    assert not writes()


def test_requires_login(api):
    c, cid = api
    c.post("/api/auth/logout")
    assert go(c, cid).status_code == 401 and c.get(f"/api/connections/{cid}/nodes/enzo/power").status_code == 401
    assert not CALLS


def test_check_is_read_only_and_describes(api):
    c, cid = api
    ST["guests"] = [guest(100)]
    r = c.get(f"/api/connections/{cid}/nodes/enzo/power").json()
    assert r["running_guests"] == [{"vmid": 100, "name": "vm100", "type": "qemu"}] and r["quorum_loss"] is False and r["nodes_online_after"] == 2
    assert not writes()


def test_audit_and_no_secret(api):
    c, cid = api
    go(c, cid)
    go(c, cid, confirm=False)
    ST["write_fail"] = True
    assert go(c, cid).status_code == 502
    log = c.get("/api/audit").json()[::-1]
    assert [(e["action"], e["status"]) for e in log] == [("node-reboot", "started"), ("node-reboot", "error"), ("node-reboot", "error")]
    assert log[0]["target"] == "node/enzo" and SECRET not in c.get("/api/audit").text


def test_assess_handles_garbage():
    a = PS.assess("n", {}, [{"vmid": None, "node": "n", "status": "running"}, {"node": "n"}], set())
    assert a["known"] is False and a["running_guests"] == [] and a["quorum_loss"] is False
