import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": "s3cr3t-value-xyz"}
CALLS: list[str] = []
FAIL: set[str] = set()
BASE = "/api2/json"


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix(BASE)
    CALLS.append(p)
    if p in FAIL:
        return httpx.Response(403, json={"data": None})
    data = {
        "/nodes/enzo/network": [
            {"iface": "vmbr1", "type": "bridge", "bridge_vlan_aware": 1, "cidr": "10.0.1.1/24"},
            {"iface": "vmbr0", "type": "bridge", "comments": "LAN"},
            {"iface": "vnetA", "type": "vnet", "zone": "z1"},          # any_bridge inclut déjà un VNet
        ],
        "/cluster/sdn/vnets": [{"vnet": "vnetA", "zone": "z1", "alias": "Serveurs"}, {"vnet": "vnetB", "zone": "z2"}],
        "/nodes/enzo/storage": [{"storage": "local", "active": 1}, {"storage": "nfs", "active": 1}, {"storage": "off", "active": 0}],
        "/nodes/enzo/storage/local/content": [{"volid": "local:iso/Debian.iso", "size": 5, "content": "iso"},
                                              {"volid": "local:iso/arch.iso", "size": 7, "content": "iso"}],
        "/nodes/enzo/storage/nfs/content": [{"volid": "nfs:iso/win.iso", "size": 9, "content": "iso"}],
    }.get(p)
    return httpx.Response(200 if data is not None else 404, json={"data": data})


@pytest.fixture
def api(client):
    CALLS.clear(); FAIL.clear()
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def test_requires_auth(client):
    assert client.get("/api/connections/1/nodes/enzo/bridges").status_code == 401
    assert client.get("/api/connections/1/nodes/enzo/isos").status_code == 401


def test_bridges_merge_bridges_and_vnets_without_duplicates(api):
    c, cid = api
    r = c.get(f"/api/connections/{cid}/nodes/enzo/bridges").json()
    assert [(b["name"], b["kind"]) for b in r] == [("vmbr0", "bridge"), ("vmbr1", "bridge"), ("vnetA", "vnet"), ("vnetB", "vnet")]
    vm1 = next(b for b in r if b["name"] == "vmbr1")
    assert vm1["vlan_aware"] is True and vm1["detail"] == "10.0.1.1/24"
    a = next(b for b in r if b["name"] == "vnetA")
    assert a["zone"] == "z1" and a["detail"] == "Serveurs"


def test_bridges_survive_missing_sdn(api):
    c, cid = api
    FAIL.add("/cluster/sdn/vnets")
    r = c.get(f"/api/connections/{cid}/nodes/enzo/bridges")
    assert r.status_code == 200 and {b["name"] for b in r.json()} == {"vmbr0", "vmbr1", "vnetA"}


def test_bridges_fail_if_local_network_unreadable(api):
    c, cid = api
    FAIL.add("/nodes/enzo/network")
    assert c.get(f"/api/connections/{cid}/nodes/enzo/bridges").status_code == 502


def test_isos_listed_across_active_storages_sorted(api):
    c, cid = api
    r = c.get(f"/api/connections/{cid}/nodes/enzo/isos").json()
    assert [i["volid"] for i in r] == ["local:iso/arch.iso", "local:iso/Debian.iso", "nfs:iso/win.iso"]
    assert "/nodes/enzo/storage/off/content" not in CALLS          # stockage inactif ignoré


def test_isos_skip_a_failing_storage(api):
    c, cid = api
    FAIL.add("/nodes/enzo/storage/nfs/content")
    assert [i["volid"] for i in c.get(f"/api/connections/{cid}/nodes/enzo/isos").json()] == ["local:iso/arch.iso", "local:iso/Debian.iso"]


@pytest.mark.parametrize("node", ["a;b", "-x", "a b"])
def test_invalid_node_rejected(api, node):
    c, cid = api
    assert c.get(f"/api/connections/{cid}/nodes/{node}/bridges").status_code in (404, 422) and CALLS == []


# ---------- modèles LXC ----------

def _tpl_handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix(BASE)
    CALLS.append(p)
    if p in FAIL:
        return httpx.Response(403, json={"data": None})
    data = {
        "/nodes/enzo/storage": [{"storage": "local", "active": 1}, {"storage": "nfs", "active": 1}, {"storage": "off", "active": 0}],
        "/nodes/enzo/storage/local/content": [{"volid": "local:vztmpl/debian-12.tar.zst", "size": 5, "content": "vztmpl"},
                                              {"volid": "local:vztmpl/alpine-3.20.tar.zst", "size": 3, "content": "vztmpl"}],
        "/nodes/enzo/storage/nfs/content": [],
        "/nodes/enzo/aplinfo": [{"template": "ubuntu-24.04-standard_24.04-2_amd64.tar.zst", "type": "lxc", "os": "ubuntu", "version": "24.04", "section": "system", "architecture": "amd64", "headline": "Ubuntu 24.04"},
                                {"template": "turnkey-core.tar.gz", "type": "lxc", "section": "turnkeylinux"}, {"template": "x", "type": "openvz"}, {"type": "lxc"}],
    }.get(p)
    return httpx.Response(200 if data is not None else 404, json={"data": data})


@pytest.fixture
def tpl(client):
    CALLS.clear(); FAIL.clear()
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_tpl_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def test_templates_require_auth(client):
    assert client.get("/api/connections/1/nodes/enzo/templates").status_code == 401


def test_templates_local_sorted_and_downloadable_filtered(tpl):
    c, cid = tpl
    r = c.get(f"/api/connections/{cid}/nodes/enzo/templates").json()
    assert r["storages"] == ["local", "nfs", "off"]
    assert [t["volid"] for t in r["local"]] == ["local:vztmpl/alpine-3.20.tar.zst", "local:vztmpl/debian-12.tar.zst"]
    assert "/nodes/enzo/storage/off/content" not in CALLS                       # stockage inactif ignoré
    assert [d["template"] for d in r["downloadable"]] == ["ubuntu-24.04-standard_24.04-2_amd64.tar.zst", "turnkey-core.tar.gz"]
    assert r["downloadable"][0]["architecture"] == "amd64" and r["downloadable"][1]["architecture"] is None
    assert r["downloadable"][0]["description"] == "Ubuntu 24.04"                  # openvz et entrées sans nom écartés


def test_templates_survive_missing_catalogue_or_failing_storage(tpl):
    c, cid = tpl
    FAIL.update({"/nodes/enzo/aplinfo": 1, "/nodes/enzo/storage/nfs/content": 1})
    r = c.get(f"/api/connections/{cid}/nodes/enzo/templates").json()
    assert r["downloadable"] is None and len(r["local"]) == 2


@pytest.mark.parametrize("node", ["a;b", "-x"])
def test_templates_invalid_node_rejected(tpl, node):
    c, cid = tpl
    assert c.get(f"/api/connections/{cid}/nodes/{node}/templates").status_code in (404, 422) and CALLS == []
