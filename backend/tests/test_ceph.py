import copy

import httpx
import pytest

from app.cephspec import (MASK, redact, shape_conf_db, shape_conf_raw, shape_fs, shape_log, shape_mgrs, shape_mons, shape_osds,
                          shape_pools, shape_status)
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}

GB = 1024 ** 3
STATUS = {
    "health": {"status": "HEALTH_WARN", "checks": {
        "OSD_DOWN": {"severity": "HEALTH_WARN", "summary": {"message": "1 osds down", "count": 1},
                     "detail": [{"message": "osd.3 (root=default,host=pve3) is down"}], "muted": False},
        "POOL_NO_REDUNDANCY": {"severity": "HEALTH_WARN", "summary": {"message": "1 pool(s) have no replicas configured", "count": 1}, "muted": True}}},
    "monmap": {"num_mons": 3}, "quorum_names": ["pve1", "pve2", "pve3"],
    "osdmap": {"num_osds": 6, "num_up_osds": 5, "num_in_osds": 6},
    "pgmap": {"num_pgs": 128, "pgs_by_state": [{"state_name": "active+clean", "count": 120}, {"state_name": "active+undersized+degraded", "count": 8}],
              "bytes_total": 6000 * GB, "bytes_used": 1500 * GB, "bytes_avail": 4500 * GB,
              "read_bytes_sec": 1000, "write_bytes_sec": 2000, "read_op_per_sec": 10, "write_op_per_sec": 20},
    "mgrmap": {"available": True, "active_name": "pve1", "standbys": [{"name": "pve2"}, {"name": "pve3"}]},
}


def osd(i, status="up", inn=1, cls="ssd", pct=24.5):
    return {"id": i, "name": f"osd.{i}", "type": "osd", "status": status, "in": inn, "device_class": cls, "crush_weight": 0.9, "reweight": 1,
            "percent_used": pct, "bytes_used": 100 * GB, "total_space": 400 * GB, "pgs": 42, "version": "19.2.0"}


OSD_TREE = {"root": {"id": -1, "name": "default", "type": "root", "children": [
    {"id": -2, "name": "pve1", "type": "host", "children": [osd(1), osd(0)]},
    {"id": -3, "name": "pve2", "type": "host", "children": [osd(2), osd(3, "down", 1)]},
    {"id": -4, "name": "pve3", "type": "host", "children": [osd(4, cls="hdd"), osd(5, inn=0)]}]}, "flags": "noout,nobackfill"}
MONS = [{"name": "pve2", "rank": 1, "addr": "10.0.0.6:6789", "host": "pve2", "quorum": 1, "ceph_version_short": "19.2.0"},
        {"name": "pve1", "rank": 0, "addr": "10.0.0.5:6789", "host": "pve1", "quorum": 1, "state": "running"}]
MGRS = [{"name": "pve2", "state": "standby", "host": "pve2"}, {"name": "pve1", "state": "active", "host": "pve1", "addr": "10.0.0.5"}]
POOLS = [{"pool_name": "vm-pool", "pool": 2, "type": "replicated", "size": 3, "min_size": 2, "pg_num": 128, "crush_rule_name": "replicated_rule",
          "pg_autoscale_mode": "on", "bytes_used": 300 * GB, "percent_used": 0.05, "application_metadata": {"rbd": {}}},
         {"pool_name": "risque", "pool": 3, "size": 1, "min_size": 1, "pg_num": 32},
         {"pool_name": "min1", "pool": 4, "size": 3, "min_size": 1},
         {"pool_name": "absurde", "pool": 5, "size": 2, "min_size": 3}]
FS = [{"name": "cephfs", "metadata_pool": "cephfs_metadata", "data_pool": "cephfs_data"}]
MDS = [{"name": "pve2", "state": "standby", "host": "pve2"}, {"name": "pve1", "rank": 0, "state": "up:active", "addr": "10.0.0.5:6800", "host": "pve1"}]
CONF = "[global]\n\tauth_client_required = cephx\n\tfsid = 1234\n\tmon_host = 10.0.0.5\n\tkeyring = /etc/pve/priv/ceph.client.admin.keyring\n\tsome_secret = hunter2\n"
CONF_DB = [{"section": "mgr", "name": "mgr/dashboard/password", "value": "hunter2", "level": "advanced", "can_update_at_runtime": 1},
           {"section": "global", "name": "osd_pool_default_size", "value": "3", "level": "advanced", "can_update_at_runtime": True}]
LOG = [{"n": 2, "t": "cluster [DBG] pgmap v2: 128 pgs"}, {"n": 1, "t": "auth key=AQBsecretXYZ== used by client.admin"}]

DATA = {"/cluster/ceph/status": STATUS, "/nodes/{n}/ceph/mon": MONS, "/nodes/{n}/ceph/mgr": MGRS, "/nodes/{n}/ceph/osd": OSD_TREE,
        "/nodes/{n}/ceph/pool": POOLS, "/nodes/{n}/ceph/fs": FS, "/nodes/{n}/ceph/mds": MDS, "/nodes/{n}/ceph/cfg/raw": CONF,
        "/nodes/{n}/ceph/cfg/db": CONF_DB, "/nodes/{n}/ceph/log": LOG}
NODES = [{"node": "pve1", "status": "online"}, {"node": "pve3", "status": "offline"}, {"node": "pve2", "status": "online"}, "illisible"]
CALLS: list[dict] = []
STATE: dict = {}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/api2/json")
    CALLS.append({"method": request.method, "path": path, "params": dict(request.url.params)})
    if path == "/nodes":
        if "/nodes" in STATE.get("fail", {}):
            code, reason, body = STATE["fail"]["/nodes"]
            return httpx.Response(code, json=body, extensions={"reason_phrase": reason.encode()})
        return httpx.Response(200, json={"data": STATE.get("nodes", NODES)})
    node = path.split("/")[2] if path.startswith("/nodes/") else None
    key = path.replace(f"/nodes/{node}/", "/nodes/{n}/") if node else path
    for k in (path, key):
        if k in STATE.get("fail", {}):
            code, reason, body = STATE["fail"][k]
            return httpx.Response(code, json=body, extensions={"reason_phrase": reason.encode()})
    if node and (node, key) in STATE.get("fail_node", {}):
        code, reason, body = STATE["fail_node"][(node, key)]
        return httpx.Response(code, json=body, extensions={"reason_phrase": reason.encode()})
    if key in DATA:
        return httpx.Response(200, json={"data": STATE.get("data", {}).get(key, DATA[key])})
    return httpx.Response(404, json={"data": None})


NOT_INSTALLED_PHRASE = (500, "binary not installed: /usr/bin/ceph-mon", {"data": None})
NOT_INSTALLED_BODY = (500, "Internal Server Error", {"data": None, "message": "binary not installed: /usr/bin/ceph-mon"})


@pytest.fixture
def api(client):
    CALLS.clear()
    STATE.clear()
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def u(cid, what, query=""):
    return f"/api/connections/{cid}/ceph/{what}{query}"


ROUTES = ["status", "monitors", "managers", "osds", "pools", "filesystems", "config", "log"]
PATHS = {"status": "/cluster/ceph/status", "monitors": "/ceph/mon", "managers": "/ceph/mgr", "osds": "/ceph/osd", "pools": "/ceph/pool",
         "filesystems": "/ceph/fs", "config": "/ceph/cfg/raw", "log": "/ceph/log"}


def all_failing(spec):
    return {"/cluster/ceph/status": spec, **{f"/nodes/{{n}}/ceph/{p}": spec for p in ("mon", "mgr", "osd", "pool", "fs", "mds", "cfg/raw", "cfg/db", "log")}}


# ============================== accès et lecture seule ==============================================================

@pytest.mark.parametrize("what", ROUTES)
def test_requires_auth(client, what):
    assert client.get(u(1, what)).status_code == 401


@pytest.mark.parametrize("what", ROUTES)
def test_unknown_connection(api, what):
    assert api[0].get(u(999, what)).status_code == 404


@pytest.mark.parametrize("what", ROUTES)
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_only_get_exists(api, what, method):
    c, cid = api
    assert getattr(c, method)(u(cid, what)).status_code == 405
    assert CALLS == []


@pytest.mark.parametrize("what", ROUTES)
def test_only_reads_are_ever_sent_to_proxmox(api, what):
    c, cid = api
    c.get(u(cid, what))
    assert CALLS and all(x["method"] == "GET" for x in CALLS)


# ============================== santé et état =======================================================================

def test_status_shaped(api):
    c, cid = api
    r = c.get(u(cid, "status")).json()
    assert r["installed"] is True and r["health"]["status"] == "HEALTH_WARN"
    down, muted = r["health"]["checks"]
    assert down == {"code": "OSD_DOWN", "severity": "HEALTH_WARN", "message": "1 osds down", "count": 1, "muted": False,
                    "details": ["osd.3 (root=default,host=pve3) is down"]}
    assert muted["code"] == "POOL_NO_REDUNDANCY" and muted["muted"] is True
    assert r["osds"] == {"total": 6, "up": 5, "in": 6}
    assert r["mons"] == {"total": 3, "quorum": ["pve1", "pve2", "pve3"]}
    assert r["mgr"] == {"active": "pve1", "standbys": 2, "available": True}
    assert r["pgs"]["total"] == 128 and r["pgs"]["all_clean"] is False and r["pgs"]["states"][1] == {"state": "active+undersized+degraded", "count": 8}
    assert r["usage"] == {"total": 6000 * GB, "used": 1500 * GB, "avail": 4500 * GB, "percent": 25.0}
    assert r["io"] == {"read_bytes_sec": 1000, "write_bytes_sec": 2000, "read_ops": 10, "write_ops": 20}
    assert CALLS[0]["path"] == "/cluster/ceph/status"


@pytest.mark.parametrize("status", ["HEALTH_OK", "HEALTH_WARN", "HEALTH_ERR"])
def test_health_values_kept(api, status):
    STATE["data"] = {"/cluster/ceph/status": {"health": {"status": status}}}
    assert api[0].get(u(api[1], "status")).json()["health"]["status"] == status


@pytest.mark.parametrize("bad", ["HEALTH_FINE", "", None, 3, [], {"x": 1}, "health_ok"])
def test_unknown_health_value_is_unknown_not_guessed(api, bad):
    STATE["data"] = {"/cluster/ceph/status": {"health": {"status": bad}}}
    assert api[0].get(u(api[1], "status")).json()["health"]["status"] == "UNKNOWN"


@pytest.mark.parametrize("junk", [None, "texte", 7, [], [1, 2], {"health": "x", "osdmap": 3, "pgmap": [], "mgrmap": "m", "monmap": None},
                                  {"health": {"checks": {"X": "a", "Y": None, "Z": {"summary": 5, "detail": "d"}}}},
                                  {"pgmap": {"pgs_by_state": ["a", None, {"count": "x"}], "bytes_total": "abc", "bytes_used": 5}}])
def test_status_tolerates_anything(api, junk):
    STATE["data"] = {"/cluster/ceph/status": junk}
    r = api[0].get(u(api[1], "status"))
    assert r.status_code == 200 and r.json()["installed"] is True


def test_status_usage_percent_is_null_when_total_unknown():
    assert shape_status({"pgmap": {"bytes_used": 5}})["usage"]["percent"] is None
    assert shape_status({"pgmap": {"bytes_used": 5, "bytes_total": 0}})["usage"]["percent"] is None


def test_all_clean_requires_pgs():
    assert shape_status({})["pgs"]["all_clean"] is False
    assert shape_status({"pgmap": {"pgs_by_state": [{"state_name": "active+clean", "count": 3}]}})["pgs"]["all_clean"] is True


# ============================== Ceph non installé ===================================================================

@pytest.mark.parametrize("what", ROUTES)
@pytest.mark.parametrize("spec", [NOT_INSTALLED_PHRASE, NOT_INSTALLED_BODY], ids=["phrase de statut", "corps"])
def test_not_installed_is_a_clear_200_never_a_raw_error(api, what, spec):
    c, cid = api
    STATE["fail"] = all_failing(spec)
    r = c.get(u(cid, what))
    assert r.status_code == 200
    assert r.json() == {"installed": False, "message": "Ceph n'est pas installé sur ce cluster."}
    assert "ceph-mon" not in r.text and "binary" not in r.text and SECRET not in r.text


@pytest.mark.parametrize("what", ROUTES)
@pytest.mark.parametrize("code,reason", [(500, "Internal Server Error"), (500, "boom"), (403, "Forbidden"), (401, "Unauthorized"), (404, "Not Found"), (502, "Bad Gateway")])
def test_other_errors_stay_errors_and_never_claim_not_installed(api, what, code, reason):
    c, cid = api
    STATE["fail"] = all_failing((code, reason, {"data": None}))
    r = c.get(u(cid, what))
    assert r.status_code == 502 and "installed" not in r.text and SECRET not in r.text


def test_the_not_installed_message_is_only_trusted_on_a_500(api):
    c, cid = api
    STATE["fail"] = all_failing((403, "binary not installed: /usr/bin/ceph-mon", {"data": None}))
    assert c.get(u(cid, "status")).status_code == 502


def test_not_installed_on_one_node_falls_back_to_the_next(api):
    c, cid = api
    STATE["fail_node"] = {("pve1", "/nodes/{n}/ceph/mon"): NOT_INSTALLED_PHRASE}
    r = c.get(u(cid, "monitors")).json()
    assert r["installed"] is True and r["node"] == "pve2" and [m["name"] for m in r["monitors"]] == ["pve1", "pve2"]
    assert [x["path"] for x in CALLS if "ceph" in x["path"]] == ["/nodes/pve1/ceph/mon", "/nodes/pve2/ceph/mon"]


def test_other_error_on_first_node_does_not_fall_back(api):
    c, cid = api
    STATE["fail_node"] = {("pve1", "/nodes/{n}/ceph/mon"): (500, "boom", {"data": None})}
    assert c.get(u(cid, "monitors")).status_code == 502
    assert all(x["path"] != "/nodes/pve2/ceph/mon" for x in CALLS)


def test_not_installed_everywhere_means_not_installed(api):
    c, cid = api
    STATE["fail"] = {"/nodes/{n}/ceph/mon": NOT_INSTALLED_PHRASE}
    assert c.get(u(cid, "monitors")).json()["installed"] is False
    assert sum(1 for x in CALLS if x["path"].endswith("/ceph/mon")) == 2          # pve1 et pve2 ; pve3 est hors ligne


# ============================== choix du nœud =======================================================================

def test_node_defaults_to_first_online_node_alphabetically(api):
    c, cid = api
    assert c.get(u(cid, "pools")).json()["node"] == "pve1"
    assert CALLS[-1]["path"] == "/nodes/pve1/ceph/pool"


def test_offline_and_unreadable_nodes_are_skipped(api):
    c, cid = api
    STATE["nodes"] = [{"node": "pve1", "status": "offline"}, {"node": "pve2", "status": "online"}, {"status": "online"}, {"node": 5, "status": "online"}, None]
    assert c.get(u(cid, "pools")).json()["node"] == "pve2"


def test_no_online_node_is_a_503(api):
    c, cid = api
    STATE["nodes"] = [{"node": "pve1", "status": "offline"}]
    assert c.get(u(cid, "pools")).status_code == 503


def test_explicit_node_is_used_without_listing_nodes(api):
    c, cid = api
    assert c.get(u(cid, "pools", "?node=pve3")).json()["node"] == "pve3"
    assert [x["path"] for x in CALLS] == ["/nodes/pve3/ceph/pool"]


def test_explicit_node_that_has_no_ceph_does_not_fall_back(api):
    c, cid = api
    STATE["fail_node"] = {("pve1", "/nodes/{n}/ceph/pool"): NOT_INSTALLED_PHRASE}
    assert c.get(u(cid, "pools", "?node=pve1")).json()["installed"] is False
    assert all(x["path"] != "/nodes/pve2/ceph/pool" for x in CALLS)


@pytest.mark.parametrize("what", ["monitors", "managers", "osds", "pools", "filesystems", "config", "log"])
@pytest.mark.parametrize("bad", ["-pve", "pve_1", "pve.1", "p" * 64, "pve%0a", "pve%2F..", "a b", "pve1;x"])
def test_invalid_node_refused_and_nothing_called(api, what, bad):
    c, cid = api
    assert c.get(u(cid, what, f"?node={bad}")).status_code == 422 and CALLS == []


# ============================== moniteurs, gestionnaires, OSD, pools ================================================

def test_monitors_sorted_by_rank(api):
    r = api[0].get(u(api[1], "monitors")).json()
    assert [m["name"] for m in r["monitors"]] == ["pve1", "pve2"]
    assert r["monitors"][0] == {"name": "pve1", "host": "pve1", "addr": "10.0.0.5:6789", "rank": 0, "in_quorum": True, "state": "running", "version": None}
    assert r["monitors"][1]["version"] == "19.2.0"


def test_managers(api):
    r = api[0].get(u(api[1], "managers")).json()["managers"]
    assert [(m["name"], m["state"]) for m in r] == [("pve1", "active"), ("pve2", "standby")]


def test_osds_flattened_with_host_and_summary(api):
    r = api[0].get(u(api[1], "osds")).json()
    assert [o["id"] for o in r["osds"]] == [0, 1, 2, 3, 4, 5]
    assert [o["host"] for o in r["osds"]] == ["pve1", "pve1", "pve2", "pve2", "pve3", "pve3"]
    assert r["osds"][3]["up"] is False and r["osds"][5]["in"] is False and r["osds"][4]["device_class"] == "hdd"
    assert r["osds"][0] == {"id": 0, "name": "osd.0", "host": "pve1", "up": True, "in": True, "device_class": "ssd", "crush_weight": 0.9,
                            "reweight": 1.0, "percent_used": 24.5, "used": 100 * GB, "total": 400 * GB, "pgs": 42, "version": "19.2.0"}
    assert r["flags"] == ["noout", "nobackfill"] and r["summary"] == {"total": 6, "up": 5, "in": 5}


@pytest.mark.parametrize("junk", [None, "x", 3, [], {"root": "x"}, {"root": {"type": "root", "children": "x"}}, {"root": {"children": [None, 5, "a", {"type": "host", "children": [{"type": "osd"}]}]}}])
def test_osds_tolerate_anything(junk):
    r = shape_osds(junk)
    assert isinstance(r["osds"], list) and r["summary"]["total"] == len(r["osds"])


def test_osd_without_status_is_unknown_not_down():
    assert shape_osds({"root": {"children": [{"type": "osd", "id": 1}]}})["osds"][0]["up"] is None
    assert shape_osds({"root": {"children": [{"type": "osd", "id": 1, "status": "garbage"}]}})["osds"][0]["up"] is False


def test_osd_tree_depth_is_bounded():
    node: dict = {"type": "osd", "id": 99, "status": "up"}
    for i in range(40):
        node = {"type": "rack", "name": f"r{i}", "children": [node]}
    assert shape_osds({"root": node})["osds"] == []                      # trop profond : ignoré, pas de récursion folle


def test_osd_tree_size_is_bounded():
    kids = [{"type": "osd", "id": i, "status": "up"} for i in range(7000)]
    assert len(shape_osds({"root": {"type": "root", "children": kids}})["osds"]) < 7000


def test_osd_flags_empty_and_odd():
    assert shape_osds({"flags": ""})["flags"] == [] and shape_osds({"flags": 5})["flags"] == [] and shape_osds({"flags": " a , ,b "})["flags"] == ["a", "b"]


def test_pools_with_redundancy_warnings(api):
    r = {p["name"]: p for p in api[0].get(u(api[1], "pools")).json()["pools"]}
    assert r["vm-pool"] == {"name": "vm-pool", "id": 2, "type": "replicated", "size": 3, "min_size": 2, "pg_num": 128, "crush_rule": "replicated_rule",
                            "autoscale": "on", "used": 300 * GB, "percent_used": 0.05, "applications": ["rbd"], "warnings": []}
    assert "size inférieur à 2" in r["risque"]["warnings"][0] and len(r["risque"]["warnings"]) == 1
    assert "min_size à 1" in r["min1"]["warnings"][0]
    assert "min_size supérieur à size" in r["absurde"]["warnings"][0]


@pytest.mark.parametrize("junk", [None, "x", 3, {}, [None, 5, "a", {}, {"pool_name": 7}, {"pool_name": "ok", "size": "abc", "application_metadata": "zz", "percent_used": "NaN"}]])
def test_pools_tolerate_anything(junk):
    assert isinstance(shape_pools(junk), list)


def test_pool_warnings_never_guess_from_missing_values():
    assert shape_pools([{"pool_name": "a"}])[0]["warnings"] == []
    assert shape_pools([{"pool_name": "a", "size": 3}])[0]["warnings"] == []


# ============================== CephFS ==============================================================================

def test_filesystems_and_mds(api):
    r = api[0].get(u(api[1], "filesystems")).json()
    assert r["filesystems"] == [{"name": "cephfs", "metadata_pool": "cephfs_metadata", "data_pools": ["cephfs_data"]}]
    assert [(m["name"], m["state"], m["rank"]) for m in r["mds"]] == [("pve1", "up:active", 0), ("pve2", "standby", None)]
    assert {x["path"] for x in CALLS if "ceph" in x["path"]} == {"/nodes/pve1/ceph/fs", "/nodes/pve1/ceph/mds"}


def test_filesystems_accept_a_list_of_data_pools():
    r = shape_fs([{"name": "f", "data_pools": ["a", "b", 5]}], None)
    assert r["filesystems"][0]["data_pools"] == ["a", "b"] and r["mds"] == []


@pytest.mark.parametrize("junk", [None, "x", 3, {}, [None, 5, {"name": 3}]])
def test_filesystems_tolerate_anything(junk):
    assert shape_fs(junk, junk) == {"filesystems": [], "mds": []}


# ============================== configuration : jamais de secret ====================================================

def test_config_secrets_are_masked(api):
    r = api[0].get(u(api[1], "config"))
    j = r.json()
    assert "hunter2" not in r.text and "AQB" not in r.text
    assert "auth_client_required = cephx" in j["conf"]["text"] and "mon_host = 10.0.0.5" in j["conf"]["text"]
    assert f"some_secret = {MASK}" in j["conf"]["text"] and f"keyring = {MASK}" in j["conf"]["text"]
    by = {e["name"]: e for e in j["entries"]}
    assert by["mgr/dashboard/password"]["value"] == MASK and by["osd_pool_default_size"]["value"] == "3"
    assert by["osd_pool_default_size"]["runtime"] is True and j["unavailable"] == []


@pytest.mark.parametrize("line", ["key = AQBabc==", "KEY=AQBabc==", "secret: abc", "my_password = abc", "api_token=abc", "client.key = xyz",
                                  "credential = x", "rgw_swift_key=zzz", "auth key=AQBzzz== used"])
def test_redact_masks_every_secret_shape(line):
    out = redact(line)
    assert MASK in out
    assert not any(s in out for s in ("AQB", "abc", "xyz", "zzz")), out


@pytest.mark.parametrize("line", ["fsid = 1234", "mon_host = 10.0.0.5", "auth_client_required = cephx", "osd_pool_default_size = 3", "public_network = 10.0.0.0/24"])
def test_redact_leaves_ordinary_settings_alone(line):
    assert redact(line) == line


def test_config_db_masks_secret_names_even_with_odd_values():
    out = shape_conf_db([{"name": "x_password", "value": "p"}, {"name": "token_x", "value": {"a": 1}}, {"name": "ok", "value": "v"}, {"name": "k_secret", "value": None}])
    by = {e["name"]: e["value"] for e in out}
    assert by == {"x_password": MASK, "token_x": None, "ok": "v", "k_secret": None}


def test_config_db_failure_is_reported_not_hidden(api):
    c, cid = api
    STATE["fail"] = {"/nodes/{n}/ceph/cfg/db": (500, "boom", {"data": None})}
    j = c.get(u(cid, "config")).json()
    assert j["installed"] is True and j["entries"] == [] and j["unavailable"] == ["db"] and j["conf"]["text"]


def test_config_raw_failure_is_an_error(api):
    c, cid = api
    STATE["fail"] = {"/nodes/{n}/ceph/cfg/raw": (500, "boom", {"data": None})}
    assert c.get(u(cid, "config")).status_code == 502


def test_config_raw_size_is_bounded():
    big = "a = b\n" * 100_000
    r = shape_conf_raw(big)
    assert r["truncated"] is True and len(r["text"]) < 250_000
    assert shape_conf_raw("a = b")["truncated"] is False and shape_conf_raw(None) == {"text": "", "truncated": False}


def test_config_lines_are_bounded_and_secret_masked_before_cutting():
    out = shape_conf_raw("key = " + "x" * 5000 + "\n" + "y" * 5000)["text"].splitlines()
    assert out[0] == f"key = {MASK}" and len(out[1]) == 500


# ============================== journal =============================================================================

def test_log_params_forwarded_and_secrets_masked(api):
    c, cid = api
    r = c.get(u(cid, "log", "?limit=50&start=10"))
    assert CALLS[-1]["params"] == {"start": "10", "limit": "50"}
    assert "AQBsecret" not in r.text
    lines = r.json()["lines"]
    assert lines[0] == {"n": 2, "text": "cluster [DBG] pgmap v2: 128 pgs"} and f"key={MASK}" in lines[1]["text"]


def test_log_defaults(api):
    api[0].get(u(api[1], "log"))
    assert CALLS[-1]["params"] == {"start": "0", "limit": "100"}


@pytest.mark.parametrize("q", ["?limit=0", "?limit=501", "?limit=-1", "?limit=abc", "?limit=", "?start=-1", "?start=abc", "?start=1000000001", "?limit=1.5"])
def test_log_invalid_params_refused_and_nothing_called(api, q):
    c, cid = api
    assert c.get(u(cid, "log", q)).status_code == 422 and CALLS == []


@pytest.mark.parametrize("q", ["?limit=1", "?limit=500", "?start=0", "?start=1000000000"])
def test_log_bounds_accepted(api, q):
    assert api[0].get(u(api[1], "log", q)).status_code == 200


@pytest.mark.parametrize("junk", [None, "x", 3, {}, [None, 5, {"n": "a"}, {"t": 5}, {"t": "ok"}]])
def test_log_tolerates_anything(junk):
    assert isinstance(shape_log(junk), list)


def test_log_lines_bounded():
    assert len(shape_log([{"t": "x" * 5000}])[0]["text"]) == 500
    assert len(shape_log([{"t": "a"}] * 5000)) == 1000


def test_invalid_value_is_not_echoed(api):
    assert "valeur-saisie-evil" not in api[0].get(u(api[1], "log", "?limit=valeur-saisie-evil")).text


# ============================== erreurs =============================================================================

@pytest.mark.parametrize("what", ROUTES)
def test_proxmox_errors_never_leak_the_token(api, what):
    c, cid = api
    STATE["fail"] = all_failing((500, "boom", {"data": None, "message": SECRET}))
    r = c.get(u(cid, what))
    assert r.status_code == 502 and SECRET not in r.text


def test_nodes_listing_error_is_502(api):
    c, cid = api
    STATE["fail"] = {"/nodes": (500, "boom", {"data": None})}
    assert c.get(u(cid, "pools")).status_code == 502


@pytest.mark.parametrize("junk", [None, "x", 3, {}, [None, 5, {"name": 1}], [{"name": "a", "rank": "x", "quorum": "maybe"}]])
def test_mons_and_mgrs_tolerate_anything(junk):
    assert isinstance(shape_mons(junk), list) and isinstance(shape_mgrs(junk), list)


def test_quorum_is_unknown_when_proxmox_does_not_say():
    assert shape_mons([{"name": "a"}])[0]["in_quorum"] is None
    assert shape_mons([{"name": "a", "quorum": 0}])[0]["in_quorum"] is False


def test_status_does_not_mutate_its_input():
    d = copy.deepcopy(STATUS)
    shape_status(d)
    assert d == STATUS


# ============================== cas complémentaires =================================================================

def test_nodes_are_tried_in_alphabetical_order(api):
    c, cid = api
    STATE["nodes"] = [{"node": "pve2", "status": "online"}, {"node": "pve1", "status": "online"}]
    assert c.get(u(cid, "pools")).json()["node"] == "pve1"


def test_config_db_saying_not_installed_is_reported_as_unavailable_not_as_a_crash(api):
    c, cid = api
    STATE["fail"] = {"/nodes/{n}/ceph/cfg/db": NOT_INSTALLED_PHRASE}
    j = c.get(u(cid, "config")).json()
    assert j["installed"] is True and j["unavailable"] == ["db"] and j["entries"] == []


def test_log_masks_every_line_not_only_the_first(api):
    c, cid = api
    STATE["data"] = {"/nodes/{n}/ceph/log": [{"n": i, "t": f"client key=AQBsecret{i}== ok"} for i in range(5)]}
    r = c.get(u(cid, "log"))
    assert "AQBsecret" not in r.text and r.text.count(MASK) == 5


def test_osd_summary_counts_unknown_states_as_neither_up_nor_in():
    """Un état inconnu n'est ni « actif » ni « dans le cluster » : on ne le compte jamais en bien (ni en mal)."""
    r = shape_osds({"root": {"children": [{"type": "osd", "id": 1, "status": "up", "in": 1}, {"type": "osd", "id": 2},
                                          {"type": "osd", "id": 3, "status": "up"}, {"type": "osd", "id": 4, "status": "down", "in": 0}]}})
    assert r["summary"] == {"total": 4, "up": 2, "in": 1}
