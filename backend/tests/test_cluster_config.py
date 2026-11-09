import httpx
import pytest

from app.clusterspec import merge_nodes, shape_corosync_nodes, shape_join, shape_qdevice, shape_status, shape_totem
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
FP = ":".join(["AB"] * 32)
DATA: dict = {}
CALLS: list[tuple[str, str]] = []


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    CALLS.append((request.method, p))
    if request.method != "GET":
        return httpx.Response(405, json={"data": None, "message": "lecture seule"})
    if p in DATA:
        v = DATA[p]
        return httpx.Response(v[0], json=v[1]) if isinstance(v, tuple) else httpx.Response(200, json={"data": v})
    return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})


@pytest.fixture
def api(client):
    DATA.clear(); CALLS.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def full():
    DATA["/cluster/status"] = [{"type": "cluster", "name": "lab", "quorate": 1, "nodes": 2, "version": 7, "id": "cluster"},
                               {"type": "node", "name": "enzo", "nodeid": 1, "online": 1, "ip": "192.168.1.200", "local": 1},
                               {"type": "node", "name": "enzo2", "nodeid": 2, "online": 1, "ip": "192.168.1.201", "local": 0}]
    DATA["/cluster/config/nodes"] = [{"name": "enzo", "nodeid": "1", "quorum_votes": "1", "ring0_addr": "192.168.1.200", "ring1_addr": "10.0.0.1", "pve_fp": FP},
                                     {"name": "enzo2", "nodeid": 2, "quorum_votes": 1, "ring0_addr": "192.168.1.201"}]
    DATA["/cluster/config/totem"] = {"cluster_name": "lab", "config_version": "7", "interface": {"0": {"linknumber": "0"}, "1": {"linknumber": "1"}}, "ip_version": "ipv4-6",
                                     "link_mode": "passive", "secauth": "on", "version": "2"}
    DATA["/cluster/config/qdevice"] = {}
    DATA["/cluster/config/join"] = {"config_digest": "a" * 40, "preferred_node": "enzo", "totem": {"cluster_name": "lab"},
                                    "nodelist": [{"name": "enzo", "nodeid": "1", "quorum_votes": "1", "ring0_addr": "192.168.1.200", "pve_addr": "192.168.1.200", "pve_fp": FP},
                                                 {"name": "enzo2", "nodeid": "2", "quorum_votes": "1", "ring0_addr": "192.168.1.201", "pve_fp": FP}]}


def test_full_summary_merges_status_and_corosync(api):
    c, cid = api
    full()
    r = c.get(f"/api/connections/{cid}/cluster/config")
    assert r.status_code == 200 and SECRET not in r.text
    j = r.json()
    assert j["cluster"] == {"name": "lab", "quorate": True, "version": 7, "nodes_total": 2, "clustered": True}
    assert j["errors"] == {} and j["qdevice"] == {"configured": False, "info": {}}
    n1, n2 = j["nodes"]
    assert (n1["name"], n1["nodeid"], n1["online"], n1["local"], n1["votes"], n1["ip"], n1["fingerprint"]) == ("enzo", 1, True, True, 1, "192.168.1.200", FP)
    assert n1["links"] == [{"link": 0, "addr": "192.168.1.200"}, {"link": 1, "addr": "10.0.0.1"}]
    assert (n2["name"], n2["local"], n2["votes"], n2["fingerprint"]) == ("enzo2", False, 1, None)
    assert j["totem"] == {"cluster_name": "lab", "config_version": 7, "ip_version": "ipv4-6", "link_mode": "passive", "secauth": "on", "transport": None, "links": [0, 1]}
    assert all(m == "GET" for m, _ in CALLS) and {p for _, p in CALLS} == {"/cluster/status", "/cluster/config/nodes", "/cluster/config/totem", "/cluster/config/qdevice", "/cluster/config/join"}
    assert j["join"] == {"preferred_node": "enzo", "address": "192.168.1.200", "fingerprint": FP, "nodes": 2}


def test_a_failing_part_does_not_break_the_others_and_never_leaks(api):
    c, cid = api
    full()
    DATA["/cluster/config/totem"] = (403, {"data": None, "message": SECRET})
    DATA["/cluster/config/qdevice"] = (500, {"data": None, "message": SECRET})
    DATA["/cluster/config/join"] = (500, {"data": None, "message": SECRET})
    r = c.get(f"/api/connections/{cid}/cluster/config")
    assert r.status_code == 200 and SECRET not in r.text
    j = r.json()
    assert j["totem"] is None and set(j["errors"]) == {"totem", "qdevice", "join"} and j["join"] is None and "Droits insuffisants" in j["errors"]["totem"]
    assert j["cluster"]["name"] == "lab" and len(j["nodes"]) == 2


def test_standalone_node_is_reported_without_cluster(api):
    c, cid = api
    DATA["/cluster/status"] = [{"type": "node", "name": "solo", "nodeid": 0, "online": 1, "ip": "10.0.0.5", "local": 1}]
    DATA["/cluster/config/nodes"] = (500, {"data": None, "message": "no corosync.conf"})
    DATA["/cluster/config/totem"] = (500, {"data": None, "message": "no corosync.conf"})
    DATA["/cluster/config/qdevice"] = {}
    DATA["/cluster/config/join"] = (500, {"data": None, "message": "no corosync.conf"})
    j = c.get(f"/api/connections/{cid}/cluster/config").json()
    assert j["cluster"]["clustered"] is False and j["cluster"]["name"] is None and j["nodes"][0]["name"] == "solo" and set(j["errors"]) == {"nodes", "totem", "join"}


def test_requires_authentication(client):
    assert client.get("/api/connections/1/cluster/config").status_code == 401


# ---------------------------------------------------------------- mise en forme (liste blanche, valeurs hostiles)
def test_status_shape_drops_junk_and_hostile_values():
    s = shape_status([{"type": "cluster", "name": "../x", "quorate": "yes", "nodes": "2", "version": True}, {"type": "node", "name": "a b", "nodeid": 1},
                      {"type": "node", "name": "ok", "nodeid": "x", "online": 1, "ip": "1.2.3.4; rm", "local": 1, "evil": SECRET}, "junk", 5, {"type": "bogus"}])
    assert s["name"] is None and s["quorate"] is None and s["version"] is None and s["nodes_total"] == 2 and s["clustered"] is True    # « 2 » lu comme entier, True refusé
    assert s["nodes"] == [{"name": "ok", "nodeid": None, "online": True, "ip": None, "local": True}]
    assert shape_status(None)["clustered"] is False and shape_status(None)["nodes"] == []


def test_corosync_shape_whitelist_and_ordering():
    raw = [{"name": "b", "nodeid": "2", "quorum_votes": "1", "ring0_addr": "10.0.0.2", "ring9_addr": "10.9.9.9", "ring2_addr": "x y", "pve_fp": "nope", "authkey": SECRET},
           {"node": "a", "nodeid": 1, "ring1_addr": "fe80::1", "ring0_addr": "10.0.0.1", "pve_addr": "10.0.0.1"}, {"name": "bad name"}, {"nodeid": 3}, "junk", None]
    out = shape_corosync_nodes(raw)
    assert [n["name"] for n in out] == ["a", "b"] and SECRET not in repr(out)
    assert out[0]["links"] == [{"link": 0, "addr": "10.0.0.1"}, {"link": 1, "addr": "fe80::1"}] and out[0]["pve_addr"] == "10.0.0.1"
    assert out[1]["links"] == [{"link": 0, "addr": "10.0.0.2"}] and out[1]["fingerprint"] is None and out[1]["votes"] == 1
    assert shape_corosync_nodes({"a": 1}) == [] and shape_corosync_nodes(None) == []
    flags = shape_corosync_nodes([{"name": "c", "nodeid": True, "quorum_votes": False}])[0]
    assert flags["nodeid"] is None and flags["votes"] is None                                                          # un booléen n'est pas un nombre


def test_totem_shape():
    assert shape_totem({}) is None and shape_totem("x") is None and shape_totem(None) is None
    t = shape_totem({"cluster_name": "a b", "config_version": "x", "interface": {"0": {}, "z": {}, "10": {}, "123": {}}, "ip_version": "x" * 50, "secauth": "on\n", "crypto_cipher": SECRET})
    assert t["cluster_name"] is None and t["config_version"] is None and t["links"] == [0, 10] and len(t["ip_version"]) == 20 and SECRET not in repr(t)
    assert t["secauth"] == "on"                                                                                       # caractères de contrôle retirés


def test_qdevice_shape_bounds_and_filters():
    assert shape_qdevice({}) == {"configured": False, "info": {}} and shape_qdevice("x") == {"configured": False, "info": {}} and shape_qdevice(None)["configured"] is False
    raw = {f"k{i}": f"v{i}" for i in range(30)}
    raw.update({"bad;key": "x", "nested": {"a": 1}, "flag": True, "state": "Connected", "votes": 1, "long": "y" * 500})
    out = shape_qdevice(raw)
    assert out["configured"] is True and len(out["info"]) <= 20 and "bad;key" not in out["info"] and "nested" not in out["info"] and "flag" not in out["info"]
    out2 = shape_qdevice({"state": "Connected", "votes": 1, "long": "y" * 500, "flag": False, "x;": "1"})
    assert out2["info"] == {"state": "Connected", "votes": "1", "long": "y" * 200}


def test_join_shape_picks_the_preferred_node_and_ignores_junk():
    assert shape_join({}) is None and shape_join("x") is None and shape_join(None) is None
    j = shape_join({"preferred_node": "b", "nodelist": [{"name": "a", "pve_addr": "10.0.0.1", "pve_fp": FP}, {"name": "b", "ring0_addr": "10.0.0.2", "pve_fp": "bad"}], "secret": SECRET})
    assert j == {"preferred_node": "b", "address": "10.0.0.2", "fingerprint": None, "nodes": 2} and SECRET not in repr(j)
    assert shape_join({"preferred_node": "zz", "nodelist": [{"name": "a", "pve_addr": "10.0.0.1"}]}) == {"preferred_node": "zz", "address": None, "fingerprint": None, "nodes": 1}
    assert shape_join({"preferred_node": "a b", "nodelist": "x"}) == {"preferred_node": None, "address": None, "fingerprint": None, "nodes": 0}


def test_merge_keeps_nodes_known_only_to_corosync():
    st = [{"name": "a", "nodeid": None, "online": True, "ip": "1.1.1.1", "local": True}]
    co = [{"name": "a", "nodeid": 1, "votes": 2, "links": [], "pve_addr": None, "fingerprint": None}, {"name": "b", "nodeid": 2, "votes": 1, "links": [], "pve_addr": "2.2.2.2", "fingerprint": None}]
    m = merge_nodes(st, co)
    assert [(n["name"], n["nodeid"], n["votes"], n["online"]) for n in m] == [("a", 1, 2, True), ("b", 2, 1, None)] and m[1]["ip"] == "2.2.2.2"
