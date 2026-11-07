"""Ceph, ÉCRITURE : initialisation (lot C5). Faux Proxmox à état : RIEN n'a tourné sur un vrai Ceph.

L'installation des paquets n'a pas d'API chez Proxmox : elle n'est pas dans ce lot. `disable_cephx` et `pg_bits` ne sont jamais transmis.
"""
from urllib.parse import quote

import httpx
import pytest

from app.cephwrite import _BUSY
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
NODES = [{"node": "pve1", "status": "online"}, {"node": "pve2", "status": "online"}, {"node": "pve5", "status": "offline"}]
CALLS: list[dict] = []
STATE: dict = {}


def _json(code, body, reason="OK"):
    return httpx.Response(code, json=body, extensions={"reason_phrase": reason.encode()})


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/api2/json")
    form = dict(httpx.QueryParams(request.content.decode())) if request.content else {}
    CALLS.append({"method": request.method, "path": path, "params": dict(request.url.params), "form": form})
    for k, (code, reason, body) in STATE.get("fail", {}).items():
        if k == f"{request.method} {path}":
            return _json(code, body, reason)
    if request.method == "GET":
        if path == "/nodes":
            return _json(200, {"data": NODES})
        if path.endswith("/ceph/cfg/raw"):
            if STATE.get("not_installed"):
                return _json(500, {"data": None, "message": "binary not installed: /usr/bin/ceph-mon\n"}, "Internal Server Error")
            if "cfg" in STATE:
                return _json(200, {"data": STATE["cfg"]})
            return _json(500, {"data": None, "message": "file '/etc/pve/ceph.conf' does not exist"}, "Internal Server Error")
    if request.method == "POST" and path.endswith("/ceph/init"):
        return _json(200, {"data": None})
    return _json(404, {"data": None})


@pytest.fixture
def api(client):
    CALLS.clear()
    STATE.clear()
    _BUSY.clear()
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()
    _BUSY.clear()


def writes():
    return [c for c in CALLS if c["method"] != "GET"]


def audit(c):
    return c.get("/api/audit").json()[::-1]


def url(cid, node="pve1"):
    return f"/api/connections/{cid}/ceph/nodes/{node}/init"


def init(c, cid, node="pve1", **kw):
    return c.post(url(cid, node), json={"network": "10.10.10.0/24", **kw})


def detail(r):
    return r.json()["detail"]


def is_confirmation(r):
    return r.status_code == 400 and detail(r).startswith("Confirmation requise (renvoie la requête avec confirm=true) : ")


# ============================== accès, et ce qui n'existe PAS ======================================================

def test_requires_auth(client):
    assert client.post(url(1), json={"network": "10.10.10.0/24"}).status_code == 401


def test_unknown_connection(api):
    c, _ = api
    assert c.post(url(999), json={"network": "10.10.10.0/24", "confirm": True}).status_code == 404 and CALLS == []


@pytest.mark.parametrize("method", ["get", "delete", "put", "patch"])
def test_no_other_verb_exists(api, method):
    c, cid = api
    assert getattr(c, method)(url(cid)).status_code in (404, 405) and CALLS == []


@pytest.mark.parametrize("node", ["bad node", "-pve", "pve1\n", "a" * 70])
def test_invalid_node_is_refused_and_nothing_is_called(api, node):
    c, cid = api
    r = c.post(url(cid, quote(node, safe="")), json={"network": "10.10.10.0/24", "confirm": True})
    assert r.status_code in (404, 405, 422) and CALLS == []


@pytest.mark.parametrize("node", ["pve9", "pve5"])
def test_unknown_or_offline_node_is_404_and_nothing_is_written(api, node):
    c, cid = api
    assert init(c, cid, node, confirm=True).status_code == 404 and writes() == []


# ============================== envoi ==============================================================================

def test_init_sends_exact_whitelisted_params(api):
    c, cid = api
    r = init(c, cid, confirm=True)
    assert r.status_code == 202 and r.json() == {"upid": None, "node": "pve1", "initialized": True}
    assert len(writes()) == 1 and writes()[0]["method"] == "POST" and writes()[0]["path"] == "/nodes/pve1/ceph/init"
    assert writes()[0]["form"] == {"network": "10.10.10.0/24", "size": "3", "min_size": "2"}


def test_init_with_cluster_network_and_values(api):
    c, cid = api
    assert init(c, cid, confirm=True, cluster_network="10.20.0.0/16", size=4, min_size=3).status_code == 202
    assert writes()[0]["form"] == {"network": "10.10.10.0/24", "size": "4", "min_size": "3", "cluster-network": "10.20.0.0/16"}


def test_network_is_normalised_to_its_network_address(api):
    c, cid = api
    init(c, cid, network="10.10.10.77/24", confirm=True)
    assert writes()[0]["form"]["network"] == "10.10.10.0/24"


def test_dangerous_and_unknown_fields_are_never_forwarded(api):
    c, cid = api
    r = init(c, cid, confirm=True, disable_cephx=True, pg_bits=6, force=1, node="pve2", name="x")
    assert r.status_code == 202
    assert set(writes()[0]["form"]) == {"network", "size", "min_size"}


def test_an_upid_returned_by_proxmox_is_kept(api):
    c, cid = api
    upid = "UPID:pve1:0001A2B3:00C4D5E6:67890ABC:cephinit::kaji@pve!kaji:"
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(
        lambda rq: _handler(rq) if not str(rq.url.path).endswith("/ceph/init") else _json(200, {"data": upid}))))
    assert init(c, cid, confirm=True).json()["upid"] == upid


# ============================== validation =========================================================================

@pytest.mark.parametrize("network", ["", "10.10.10.0", "10.10.10.0/", "/24", "10.10.10.0/33", "10.10.10.0/7", "10.10.10.0/31", "10.10.10.0/32",
                                     "0.0.0.0/8", "127.0.0.0/8", "224.0.0.0/8", "169.254.0.0/16", "abc/24", "10.10.10.0/24 ", " 10.10.10.0/24",
                                     "10.10.10.0/24\n", "10.10.10.0/24;ls", "10.10.10.0/-1", "999.1.1.0/24", "fe80::/64", "::/32", "ff00::/32",
                                     "2001:db8::/20", "10.0.0.0/24,10.1.0.0/24", "10.10.10.0/２4", "example.com/24", "10.10.10.0/255.255.255.0", "10.10.10.0/0.0.0.255"])
def test_invalid_network_is_refused_and_nothing_is_called(api, network):
    c, cid = api
    assert init(c, cid, network=network, confirm=True).status_code == 422 and CALLS == []


@pytest.mark.parametrize("extra", [{"cluster_network": "nope"}, {"cluster_network": "127.0.0.0/8"}, {"size": 1}, {"min_size": 1}, {"size": 8},
                                   {"size": 2, "min_size": 3}, {"size": "x"}, {"cluster_network": "10.10.10.0/24"}, {"cluster_network": "10.10.10.9/24"},
                                   {"network": None}, {"confirm": "true"}, {"confirm": 1}])
def test_invalid_values_are_refused_and_nothing_is_called(api, extra):
    c, cid = api
    body = {"network": "10.10.10.0/24", "confirm": True, **extra}
    assert c.post(url(cid), json=body).status_code == 422 and CALLS == []


def test_valid_ipv6_network_is_accepted(api):
    c, cid = api
    assert init(c, cid, network="fd00:10::/64", confirm=True).status_code == 202
    assert writes()[0]["form"]["network"] == "fd00:10::/64"


def test_invalid_value_is_not_echoed(api):
    c, cid = api
    r = init(c, cid, network="10.10.10.0/24;" + SECRET, confirm=True)
    assert r.status_code == 422 and SECRET not in r.text


# ============================== confirmation =======================================================================

def test_init_needs_a_server_side_confirmation_and_writes_nothing(api):
    c, cid = api
    r = init(c, cid)
    assert is_confirmation(r) and "TOUT le cluster" in detail(r) and writes() == []
    assert init(c, cid, confirm=False).status_code == 400 and writes() == []


def test_confirm_is_never_forwarded_to_proxmox(api):
    c, cid = api
    init(c, cid, confirm=True)
    assert all("confirm" not in w["form"] and "confirm" not in w["params"] for w in writes())


def test_a_public_network_adds_a_reason(api):
    c, cid = api
    assert "PAS un réseau privé" not in detail(init(c, cid))
    assert "PAS un réseau privé" in detail(init(c, cid, network="8.8.8.0/24"))
    assert "PAS un réseau privé" in detail(init(c, cid, cluster_network="8.8.4.0/24"))


def test_size_two_adds_a_reason(api):
    c, cid = api
    assert "size vaut 2" in detail(init(c, cid, size=2))
    assert "size vaut 2" not in detail(init(c, cid, size=3))


def test_confirmation_does_not_bypass_the_other_refusals(api):
    c, cid = api
    STATE["cfg"] = "[global]\n  fsid = abc\n"
    assert init(c, cid, confirm=True).status_code == 409 and writes() == []
    STATE.clear()
    STATE["not_installed"] = True
    assert init(c, cid, confirm=True).status_code == 409 and writes() == []


# ============================== états de Ceph ======================================================================

def test_already_initialised_is_409_and_nothing_is_written(api):
    c, cid = api
    STATE["cfg"] = f"[global]\n  fsid = abc\n  secret = {SECRET}\n"
    r = init(c, cid, confirm=True)
    assert r.status_code == 409 and "déjà initialisé" in detail(r) and writes() == [] and SECRET not in r.text
    assert SECRET not in c.get("/api/audit").text


@pytest.mark.parametrize("cfg", ["", "   \n", "\n\n"])
def test_an_empty_configuration_is_not_an_initialised_ceph(api, cfg):
    c, cid = api
    STATE["cfg"] = cfg
    assert init(c, cid, confirm=True).status_code == 202


def test_an_unreadable_configuration_is_the_expected_state_before_init(api):
    c, cid = api
    assert init(c, cid, confirm=True).status_code == 202          # le faux répond 500 « file does not exist »


def test_not_installed_is_409_with_the_install_hint_and_no_raw_text(api):
    c, cid = api
    STATE["not_installed"] = True
    r = init(c, cid, confirm=True)
    assert r.status_code == 409 and "pveceph install" in detail(r) and writes() == []
    assert "binary" not in r.text and "ceph-mon" not in r.text


# ============================== une écriture à la fois =============================================================

def test_one_ceph_write_at_a_time(api):
    c, cid = api
    _BUSY.add(cid)
    r = init(c, cid, confirm=True)
    assert r.status_code == 409 and "autre écriture" in detail(r) and CALLS == []


def test_the_slot_is_released_after_success_refusal_and_error(api):
    c, cid = api
    assert init(c, cid, confirm=True).status_code == 202 and not _BUSY
    assert init(c, cid).status_code == 400 and not _BUSY
    STATE["fail"] = {"POST /nodes/pve1/ceph/init": (500, "boom", {"data": None})}
    assert init(c, cid, confirm=True).status_code in (500, 502) and not _BUSY
    STATE["fail"] = {}
    assert init(c, cid, confirm=True).status_code == 202


# ============================== audit ==============================================================================

def test_audit_records_success_every_refusal_and_error(api):
    c, cid = api
    init(c, cid)                                                           # confirmation requise
    init(c, cid, "pve9", confirm=True)                                     # nœud inconnu
    init(c, cid, confirm=True, cluster_network="10.20.0.0/16")             # succès
    STATE["fail"] = {"POST /nodes/pve1/ceph/init": (500, "boom", {"data": f"token {SECRET}"})}
    init(c, cid, confirm=True)                                             # erreur Proxmox
    log = audit(c)
    assert [(e["action"], e["status"]) for e in log] == [("ceph-init", "error"), ("ceph-init", "error"), ("ceph-init", "started"), ("ceph-init", "error")]
    assert "Confirmation requise" in log[0]["detail"] and "10.10.10.0/24" in log[2]["detail"] and "10.20.0.0/16" in log[2]["detail"]
    assert SECRET not in c.get("/api/audit").text


def test_proxmox_error_text_never_reaches_the_user(api):
    c, cid = api
    STATE["fail"] = {"POST /nodes/pve1/ceph/init": (500, "boom", {"data": None, "message": f"token {SECRET}"})}
    r = init(c, cid, confirm=True)
    assert r.status_code in (500, 502) and SECRET not in r.text
