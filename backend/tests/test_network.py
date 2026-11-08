import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.networkspec import (shape_aliases, shape_interfaces, shape_ipset_entries, shape_named, shape_network, shape_options, shape_rules)
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
DIGEST = "da39a3ee5e6b4b0d3255bfef95601890afd80709"
SEEN: list[httpx.Request] = []
ST: dict = {}

IFACES = [
    {"iface": "vmbr0", "type": "bridge", "active": 1, "autostart": 1, "method": "static", "address": "192.168.1.200", "netmask": "24", "cidr": "192.168.1.200/24",
     "gateway": "192.168.1.1", "bridge_ports": "nic0", "bridge_vlan_aware": 1, "bridge_vids": "2-4094", "families": ["inet"], "priority": 3, "evil": "x"},
    {"iface": "nic0", "type": "eth", "active": 1, "method": "manual", "mtu": 1500},
    {"iface": "bond0", "type": "bond", "slaves": "nic1 nic2", "bond_mode": "802.3ad", "method": "manual", "comments": "agrégat\x07"},
    {"iface": "vmbr0.20", "type": "vlan", "vlan-id": 20, "vlan-raw-device": "vmbr0", "method": "static", "address": "10.20.0.1"},
    {"iface": "lo", "type": "loopback-inconnu", "method": "loopback"}, {"iface": "a b"}, {"iface": ""}, {"type": "eth"}, "x", None,
]
RULES = [{"pos": 1, "type": "in", "action": "ACCEPT", "enable": 1, "proto": "tcp", "dport": "22", "source": "+admins", "comment": "SSH", "log": "info", "ipversion": 4},
         {"pos": 0, "type": "group", "action": "web", "enable": 0}, {"pos": -1, "type": "in"}, {"type": "in"}, {"pos": 2, "type": "evil", "action": "A B", "log": "bruit"}, "x"]


def _handler(request: httpx.Request) -> httpx.Response:
    SEEN.append(request)
    p = request.url.path.removeprefix("/api2/json")
    if request.method != "GET":
        return httpx.Response(405, json={"data": None, "message": "écriture refusée par le faux Proxmox"})
    if ST.get("down") and "/firewall" in p and ST["down"] in p:
        return httpx.Response(403, json={"data": None, "message": SECRET})
    if ST.get("down") == "all":
        return httpx.Response(500, json={"data": None, "message": SECRET})
    table = {
        "/nodes/enzo/network": {"data": IFACES, "changes": ST.get("changes", "")},
        "/cluster/firewall/options": {"data": {"enable": 1, "policy_in": "DROP", "policy_out": "ACCEPT", "policy_forward": "ACCEPT", "digest": DIGEST, "autre": 1}},
        "/cluster/firewall/rules": {"data": RULES}, "/cluster/firewall/aliases": {"data": [{"name": "lan", "cidr": "192.168.1.0/24", "comment": "LAN"}, {"name": "a b"}, {"cidr": "x"}]},
        "/cluster/firewall/ipset": {"data": [{"name": "admins", "comment": "Admins"}, {"name": "../x"}]},
        "/cluster/firewall/groups": {"data": [{"group": "web", "comment": "Web"}]},
        "/cluster/firewall/ipset/admins": {"data": [{"cidr": "10.0.0.0/24", "comment": "x", "nomatch": 0}, {"cidr": "10.1.0.1", "nomatch": 1}, {"nocidr": 1}]},
        "/cluster/firewall/groups/web": {"data": RULES[:2]},
        "/nodes/enzo/firewall/options": {"data": {"enable": 0, "log_level_in": "info", "nf_conntrack_max": "262144", "digest": DIGEST, "libre": 1}},
        "/nodes/enzo/firewall/rules": {"data": []},
        "/nodes/enzo/qemu/115/firewall/options": {"data": {"enable": 1, "policy_in": "DROP", "macfilter": 1, "digest": "pas-un-digest"}},
        "/nodes/enzo/qemu/115/firewall/rules": {"data": RULES[:1]},
    }
    if p in table:
        return httpx.Response(200, json=table[p])
    return httpx.Response(404, json={"data": None, "message": "route inconnue du faux Proxmox"})


@pytest.fixture
def api(client):
    SEEN.clear(); ST.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def u(cid, tail):
    return f"/api/connections/{cid}{tail}"


def only_gets():
    return all(r.method == "GET" for r in SEEN)


# ---------------------------------------------------------------- réseau
def test_network_shape_and_pending_changes(api):
    c, cid = api
    ST["changes"] = "--- /etc/network/interfaces\n+++ /etc/network/interfaces.new\n+auto vmbr1"
    r = c.get(u(cid, "/nodes/enzo/network"))
    j = r.json()
    assert r.status_code == 200 and j["pending"] is True and "interfaces.new" in j["changes"]
    names = [i["iface"] for i in j["interfaces"]]
    assert names == ["vmbr0", "bond0", "nic0", "vmbr0.20", "lo"]                                # ponts, bonds, cartes, VLAN, puis le reste ; les entrées illisibles sont écartées
    assert "a b" not in names and "" not in names and len(names) == 5
    vm = next(i for i in j["interfaces"] if i["iface"] == "vmbr0")
    assert vm["bridge_ports"] == ["nic0"] and vm["bridge_vlan_aware"] is True and vm["has_gateway"] is True and "evil" not in vm and "families" not in vm
    assert next(i for i in j["interfaces"] if i["iface"] == "bond0")["slaves"] == ["nic1", "nic2"]
    assert next(i for i in j["interfaces"] if i["iface"] == "bond0")["comments"] == "agrégat"       # caractère de contrôle retiré
    assert next(i for i in j["interfaces"] if i["iface"] == "lo")["type"] == "unknown"
    assert next(i for i in j["interfaces"] if i["iface"] == "vmbr0.20")["vlan_id"] == 20 and only_gets()


def test_network_without_changes(api):
    c, cid = api
    j = c.get(u(cid, "/nodes/enzo/network")).json()
    assert j["pending"] is False and j["changes"] == ""


@pytest.mark.parametrize("node", ["a b", "-x", "a;b", "x" * 70, "a_b"])
def test_network_node_validated(api, node):
    c, cid = api
    assert c.get(u(cid, f"/nodes/{node}/network")).status_code == 422 and not SEEN


def test_network_shape_is_defensive():
    assert shape_network(None) == {"interfaces": [], "changes": None, "pending": False}
    assert shape_network({"data": "x", "changes": 5}) == {"interfaces": [], "changes": None, "pending": False}
    assert shape_network({"data": [], "changes": "  \n"})["pending"] is False
    big = shape_network({"data": [], "changes": "x" * 50000})
    assert len(big["changes"]) == 20000
    rows = shape_interfaces([{"iface": "eth0", "mtu": 10}, {"iface": "eth1", "mtu": 70000}, {"iface": "eth2", "mtu": "1500"}, {"iface": "e" * 50}])
    assert [r["mtu"] for r in rows] == [None, None, 1500] and len(rows) == 3


# ---------------------------------------------------------------- pare-feu
def test_cluster_firewall_overview(api):
    c, cid = api
    j = c.get(u(cid, "/firewall/cluster")).json()
    assert j["options"] == {"enable": True, "policy_forward": "ACCEPT", "policy_in": "DROP", "policy_out": "ACCEPT", "digest": DIGEST}
    assert "autre" not in j["options"]
    assert [r["pos"] for r in j["rules"]] == [0, 1, 2] and j["rules"][1]["dport"] == "22" and j["rules"][1]["ipversion"] == 4
    assert j["rules"][0]["type"] == "group" and j["rules"][0]["action"] == "web" and j["rules"][0]["enable"] is False
    assert j["rules"][2]["type"] is None and j["rules"][2]["action"] is None and j["rules"][2]["log"] is None        # valeurs hors liste : écartées
    assert j["aliases"] == [{"name": "lan", "cidr": "192.168.1.0/24", "comment": "LAN"}]
    assert j["ipsets"] == [{"name": "admins", "comment": "Admins"}] and j["groups"] == [{"name": "web", "comment": "Web"}] and only_gets()


def test_ipset_entries_and_group_rules(api):
    c, cid = api
    assert c.get(u(cid, "/firewall/cluster/ipsets/admins")).json() == [{"cidr": "10.0.0.0/24", "comment": "x", "nomatch": False}, {"cidr": "10.1.0.1", "comment": None, "nomatch": True}]
    assert [r["pos"] for r in c.get(u(cid, "/firewall/cluster/groups/web")).json()] == [0, 1]


@pytest.mark.parametrize("name", ["a b", "../x", "a;b", "-x", "x" * 70, "a%2Fb"])
def test_named_paths_validated(api, name):
    c, cid = api
    assert c.get(u(cid, f"/firewall/cluster/ipsets/{name}")).status_code in (404, 422) and c.get(u(cid, f"/firewall/cluster/groups/{name}")).status_code in (404, 422)
    assert not [r for r in SEEN if "x" in r.url.path.split("/")[-1] and ".." in r.url.path]


def test_node_and_guest_firewall(api):
    c, cid = api
    n = c.get(u(cid, "/firewall/nodes/enzo")).json()
    assert n["options"]["enable"] is False and n["options"]["log_level_in"] == "info" and n["options"]["nf_conntrack_max"] == 262144 and "libre" not in n["options"] and n["rules"] == []
    g = c.get(u(cid, "/firewall/guests/enzo/qemu/115")).json()
    assert g["options"]["policy_in"] == "DROP" and g["options"]["macfilter"] is True and g["options"]["digest"] is None and len(g["rules"]) == 1       # digest illisible : écarté


@pytest.mark.parametrize("path", ["/firewall/guests/enzo/vz/115", "/firewall/guests/enzo/qemu/99", "/firewall/guests/enzo/qemu/abc", "/firewall/guests/a b/qemu/115", "/firewall/nodes/a;b"])
def test_guest_and_node_paths_validated(api, path):
    c, cid = api
    assert c.get(u(cid, path)).status_code == 422 and not SEEN


def test_a_failing_part_does_not_break_the_others_and_never_leaks(api):
    c, cid = api
    ST["down"] = "/cluster/firewall/rules"
    j = c.get(u(cid, "/firewall/cluster")).json()
    assert "error" in j["rules"] and j["options"]["policy_in"] == "DROP" and j["aliases"] and SECRET not in str(j)


def test_total_failure_is_translated(api):
    c, cid = api
    ST["down"] = "all"
    r = c.get(u(cid, "/nodes/enzo/network"))
    assert r.status_code == 502 and SECRET not in r.text


def test_nothing_is_ever_written(api):
    c, cid = api
    for tail in ("/nodes/enzo/network", "/firewall/cluster", "/firewall/nodes/enzo", "/firewall/guests/enzo/qemu/115", "/firewall/cluster/ipsets/admins", "/firewall/cluster/groups/web"):
        c.get(u(cid, tail))
    assert SEEN and only_gets()
    for method in ("post", "put", "delete", "patch"):
        assert getattr(c, method)(u(cid, "/firewall/cluster")).status_code in (404, 405, 422)
        assert getattr(c, method)(u(cid, "/nodes/enzo/network")).status_code in (404, 405, 422)


def test_requires_login(client):
    for tail in ("/nodes/enzo/network", "/firewall/cluster", "/firewall/nodes/enzo", "/firewall/guests/enzo/qemu/115", "/firewall/cluster/ipsets/x", "/firewall/cluster/groups/x"):
        assert client.get(u(1, tail)).status_code == 401


# ---------------------------------------------------------------- unités
def test_option_shapes_by_level():
    assert shape_options("cluster", {"policy_in": "ALLOW", "policy_forward": "REJECT", "enable": "1", "ebtables": "maybe"}) == {
        "enable": True, "ebtables": None, "policy_forward": None, "policy_in": None, "digest": None}
    assert shape_options("node", None) == {"digest": None}
    assert shape_options("guest", {"enable": 0, "radv": True, "nf_conntrack_max": 5})["enable"] is False and "nf_conntrack_max" not in shape_options("guest", {"nf_conntrack_max": 5})


def test_rule_aliases_and_entries_are_bounded():
    r = shape_rules([{"pos": 1, "comment": "x" * 500, "source": "y" * 500, "dport": "z" * 500, "action": "a" * 60}])[0]
    assert len(r["comment"]) == 200 and len(r["source"]) == 200 and len(r["dport"]) == 60 and r["action"] is None
    assert shape_aliases([{"name": "ok", "cidr": "c" * 100}])[0]["cidr"] == "c" * 60 and shape_named("x", "name") == [] and shape_ipset_entries(None) == []


def test_edge_cases_found_by_mutations():
    # plus de 1000 lignes : bornées
    assert len(shape_rules([{"pos": i} for i in range(1500)])) == 1000 and len(shape_interfaces([{"iface": f"e{i}"} for i in range(1500)])) == 1000
    # une passerelle IPv6 seule suffit à marquer l'interface d'administration
    assert shape_interfaces([{"iface": "vmbr6", "gateway6": "fe80::1"}])[0]["has_gateway"] is True and shape_interfaces([{"iface": "v"}])[0]["has_gateway"] is False
    # ipversion : seulement 4 ou 6
    assert [r["ipversion"] for r in shape_rules([{"pos": 1, "ipversion": 5}, {"pos": 2, "ipversion": 6}, {"pos": 3, "ipversion": "4"}])] == [None, 6, 4]
    # alias triés par nom ; entrées d'IPSet : cidr texte borné, autre type écarté
    assert [a["name"] for a in shape_aliases([{"name": "zeta"}, {"name": "alpha"}, {"name": "mid"}])] == ["alpha", "mid", "zeta"]
    e = shape_ipset_entries([{"cidr": "c" * 100}, {"cidr": 5}, {"cidr": ""}, {"cidr": "10.0.0.0/8", "nomatch": "1"}])
    assert [x["cidr"] for x in e] == ["10.0.0.0/8", "c" * 60] and e[0]["nomatch"] is True
