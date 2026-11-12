"""Ceph, DESTRUCTION (lot C4) : faux Proxmox STRICT à état (méthode, chemin, paramètres exacts). RIEN n'a tourné sur un vrai Ceph.

Chaque garde-fou est testé SÉPARÉMENT (et cassé volontairement : voir la PR).
"""
import copy
import re

import httpx
import pytest

from app.cephdestroy import pool_plan
from app.cephwrite import _BUSY
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
UPID = "UPID:pve1:0001A2B3:00C4D5E6:67890ABC:cephdestroy:x:kaji@pve!kaji:"
CALLS: list[dict] = []
STATE: dict = {}


def _osd(i, up=False, inn=False, pgs=0):
    return {"type": "osd", "id": i, "name": f"osd.{i}", "status": "up" if up else "down", "in": 1 if inn else 0, "device_class": "ssd", "pgs": pgs}


def tree():
    hosts = {"pve1": [_osd(0, True, True, 40), _osd(1)], "pve2": [_osd(2, True, True, 40)], "pve3": [_osd(3, True, True, 40)], "pve4": [_osd(4, True, False, 0), _osd(5, False, True, 0)],
             "pve5": [_osd(6, False, False, None)]}
    return {"root": {"type": "root", "name": "default", "children": [{"type": "host", "name": h, "children": o} for h, o in hosts.items()]}}


def fresh():
    STATE.clear()
    STATE.update(
        health="HEALTH_OK", clean=True, not_installed=False,
        mons=[{"name": n, "host": n, "addr": "10.0.0.1", "rank": i, "quorum": True, "state": "running"} for i, n in enumerate(("pve1", "pve2", "pve3", "pve4"))],
        mgrs=[{"name": n, "host": n, "state": "active" if n == "pve1" else "standby"} for n in ("pve1", "pve2", "pve3", "pve4")],
        mds=[{"name": "pve1", "host": "pve1", "state": "up:active"}, {"name": "pve2", "host": "pve2", "state": "up:standby"}],
        osd=tree(), fs=[{"name": "cephfs", "metadata_pool": "cephfs_metadata", "data_pool": "cephfs_data"}],
        pools=[{"pool_name": n, "pool": i, "type": "replicated", "size": 3, "min_size": 2, "pg_num": 32, "crush_rule_name": "replicated_rule", "pg_autoscale_mode": "on",
                "application_metadata": {"rbd": {}}, "bytes_used": 0} for i, n in enumerate(("vm-pool", "other", "cephfs_data", "cephfs_metadata"))],
        storages=[{"storage": "ceph-vm", "type": "rbd", "pool": "vm-pool"}, {"storage": "local", "type": "dir"}], content={"ceph-vm": []}, content_fail=set(), deleted=[],
    )


NODES = [{"node": n, "status": "online"} for n in ("pve1", "pve2", "pve3", "pve4", "pve5")] + [{"node": "pve6", "status": "offline"}]


def _json(code, body, reason="OK"):
    return httpx.Response(code, json=body, extensions={"reason_phrase": reason.encode()})


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/api2/json")
    params = dict(request.url.params)
    form = dict(httpx.QueryParams(request.content.decode())) if request.content else {}
    CALLS.append({"method": request.method, "path": path, "params": params, "form": form})
    s = STATE
    if request.method == "GET":
        if path == "/nodes":
            return _json(200, {"data": NODES})
        if path == "/storage":
            return _json(200, {"data": copy.deepcopy(s["storages"])})
        m = re.fullmatch(r"/nodes/[a-z0-9]+/storage/([A-Za-z0-9\-_.]+)/content", path)
        if m:
            if m.group(1) in s["content_fail"] or m.group(1) not in s["content"]:
                return _json(500, {"data": None, "message": SECRET}, "Internal Server Error")
            return _json(200, {"data": copy.deepcopy(s["content"][m.group(1)])})
        if s["not_installed"] and "ceph" in path:
            return _json(500, {"data": None, "message": "binary not installed: /usr/bin/ceph-mon\n"}, "Internal Server Error")
        if path == "/cluster/ceph/status":
            states = [{"state_name": "active+clean", "count": 100}] + ([] if s["clean"] else [{"state_name": "active+remapped+backfilling", "count": 3}])
            return _json(200, {"data": {"health": {"status": s["health"]}, "pgmap": {"num_pgs": 103, "pgs_by_state": states}}})
        for suffix, key in (("/ceph/mon", "mons"), ("/ceph/mgr", "mgrs"), ("/ceph/mds", "mds"), ("/ceph/osd", "osd"), ("/ceph/pool", "pools"), ("/ceph/fs", "fs")):
            if re.fullmatch(rf"/nodes/[a-z0-9]+{suffix}", path):
                return _json(200, {"data": copy.deepcopy(s[key])})
        return _json(404, {"data": None})
    if request.method == "DELETE":
        if form:
            return _json(400, {"data": None, "message": "aucun corps attendu"}, "Bad Request")
        if (m := re.fullmatch(r"/nodes/[a-z0-9]+/ceph/pool/([A-Za-z0-9_.\-]+)", path)):
            if set(params) - {"remove_storages"} or params.get("remove_storages", "0") not in ("0", "1") or "force" in params:
                return _json(400, {"data": None, "message": f"paramètres refusés {sorted(params)}"}, "Bad Request")
            s["deleted"].append(("pool", m.group(1)))
            return _json(200, {"data": UPID})
        if (m := re.fullmatch(r"/nodes/[a-z0-9]+/ceph/osd/(\d+)", path)):
            if set(params) != {"cleanup"} or params["cleanup"] not in ("0", "1"):
                return _json(400, {"data": None, "message": f"paramètres refusés {sorted(params)}"}, "Bad Request")
            s["deleted"].append(("osd", int(m.group(1))))
            return _json(200, {"data": UPID})
        if (m := re.fullmatch(r"/nodes/[a-z0-9]+/ceph/(mon|mgr|mds)/([A-Za-z0-9\-]+)", path)):
            if params:
                return _json(400, {"data": None, "message": f"paramètres refusés {sorted(params)}"}, "Bad Request")
            s["deleted"].append((m.group(1), m.group(2)))
            return _json(200, {"data": UPID})
    return _json(404, {"data": None})


@pytest.fixture
def api(client):
    CALLS.clear()
    _BUSY.clear()
    fresh()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def u(cid, p):
    return f"/api/connections/{cid}/ceph/{p}"


def dels():
    return [c for c in CALLS if c["method"] == "DELETE"]


def audit_pairs(c):
    return [(a["action"], a["status"]) for a in c.get("/api/audit").json()]


def kill(c, cid, p, name, **q):
    return c.delete(u(cid, p), params={"confirm": "true", "name": name, **q})


def preview(c, cid, p, **q):
    r = c.delete(u(cid, p), params={"dry_run": "true", **q})
    assert r.status_code == 200, r.text
    return r.json()


# ================================================================ pool
def test_pool_destroy_sends_exactly_the_documented_call(api):
    c, cid = api
    STATE["storages"] = [{"storage": "local", "type": "dir"}]
    r = kill(c, cid, "pools/other", "other")
    assert r.status_code == 202 and r.json()["upid"] == UPID and r.json()["node"] == "pve1"
    assert dels() == [{"method": "DELETE", "path": "/nodes/pve1/ceph/pool/other", "params": {"remove_storages": "0"}, "form": {}}]
    assert STATE["deleted"] == [("pool", "other")] and ("ceph-pool-destroy", "started") in audit_pairs(c)


def test_pool_destroy_needs_confirm_then_the_retyped_name(api):
    c, cid = api
    r = c.delete(u(cid, "pools/other"), params={"name": "other"})
    assert r.status_code == 400 and "TOUTES ses données" in r.json()["detail"]
    r = c.delete(u(cid, "pools/other"), params={"confirm": "true"})
    assert r.status_code == 400 and "retape exactement other" in r.json()["detail"]
    for bad in ("Other", "other ", "vm-pool", ""):
        assert kill(c, cid, "pools/other", bad).status_code == 400
    assert not dels()


def test_pool_dry_run_writes_nothing_and_lists_blockers_and_risks(api):
    c, cid = api
    j = preview(c, cid, "pools/vm-pool")
    assert j["dry_run"] and j["expected_name"] == "vm-pool" and j["storages"] == ["ceph-vm"] and not dels()
    assert any("remove_storages=true" in b for b in j["blockers"]) and any("TOUTES ses données" in x for x in j["risks"])


def test_pool_unknown_is_404_and_ceph_missing_is_409(api):
    c, cid = api
    assert kill(c, cid, "pools/zzz", "zzz").status_code == 404
    STATE["not_installed"] = True
    r = kill(c, cid, "pools/other", "other")
    assert r.status_code == 409 and "pas installé" in r.json()["detail"] and not dels()


@pytest.mark.parametrize("name", [".mgr", "a b", "-x", "x" * 64])
def test_pool_name_is_validated_in_the_path(api, name):
    c, cid = api
    assert c.delete(u(cid, f"pools/{name}"), params={"confirm": "true", "name": name}).status_code in (404, 422) and not dels()


@pytest.mark.parametrize("health", ["HEALTH_WARN", "HEALTH_ERR", "HEALTH_UNKNOWN"])
def test_pool_refused_unless_health_ok_even_confirmed(api, health):
    c, cid = api
    STATE["health"] = health
    STATE["storages"] = []
    r = kill(c, cid, "pools/other", "other")
    assert r.status_code == 409 and "HEALTH_OK" in r.json()["detail"] and not dels()
    assert audit_pairs(c)[-1] == ("ceph-pool-destroy", "error")


@pytest.mark.parametrize("pool", ["cephfs_data", "cephfs_metadata"])
def test_pool_used_by_a_cephfs_is_refused_even_confirmed(api, pool):
    c, cid = api
    r = kill(c, cid, f"pools/{pool}", pool, remove_storages="true")
    assert r.status_code == 409 and "CephFS cephfs" in r.json()["detail"] and not dels()


def test_pool_with_volumes_is_refused_even_with_remove_storages(api):
    c, cid = api
    STATE["content"]["ceph-vm"] = [{"volid": "ceph-vm:vm-100-disk-0", "vmid": 100}, {"volid": "ceph-vm:vm-101-disk-0", "vmid": 101}, {"volid": "ceph-vm:x"}]
    r = kill(c, cid, "pools/vm-pool", "vm-pool", remove_storages="true")
    assert r.status_code == 409 and "3 volume(s)" in r.json()["detail"] and "100" in r.json()["detail"] and not dels()


def test_pool_with_unreadable_storage_content_is_refused(api):
    c, cid = api
    STATE["content_fail"] = {"ceph-vm"}
    r = kill(c, cid, "pools/vm-pool", "vm-pool", remove_storages="true")
    assert r.status_code == 409 and "impossible de lister" in r.json()["detail"] and SECRET not in r.text and not dels()


def test_pool_with_a_storage_needs_remove_storages(api):
    c, cid = api
    r = kill(c, cid, "pools/vm-pool", "vm-pool")
    assert r.status_code == 409 and "remove_storages=true" in r.json()["detail"] and not dels()
    r = kill(c, cid, "pools/vm-pool", "vm-pool", remove_storages="true")
    assert r.status_code == 202 and dels()[0]["params"] == {"remove_storages": "1"}
    assert audit_pairs(c)[0] == ("ceph-pool-destroy", "started")                      # le journal est du plus récent au plus ancien


def test_pool_ignores_storages_of_other_pools_types_and_bad_names(api):
    c, cid = api
    STATE["storages"] = [{"storage": "x", "type": "rbd", "pool": "other-pool"}, {"storage": "cfs", "type": "cephfs", "pool": "other"}, {"storage": "../etc", "type": "rbd", "pool": "other"},
                         {"storage": 5, "type": "rbd", "pool": "other"}, "junk"]
    assert kill(c, cid, "pools/other", "other").status_code == 202
    assert not [c for c in CALLS if "/storage/" in c["path"]]                      # aucun contenu lu pour un nom invalide ou un autre pool


def test_pool_with_data_says_so_in_the_confirmation(api):
    c, cid = api
    STATE["pools"][1]["bytes_used"] = 5 * 2**30
    STATE["storages"] = []
    r = c.delete(u(cid, "pools/other"), params={"name": "other"})
    assert r.status_code == 400 and "5120 Mio" in r.json()["detail"]


def test_pool_never_sends_force(api):
    c, cid = api
    STATE["storages"] = []
    assert kill(c, cid, "pools/other", "other", force="true").status_code == 202
    assert "force" not in dels()[0]["params"]


def test_pool_plan_refuses_internal_pools():
    b, _ = pool_plan({"name": ".mgr", "used": 0}, "HEALTH_OK", [], [], {}, False)
    assert any("pool interne" in x for x in b)
    b, _ = pool_plan({"name": "ok", "used": 0}, "HEALTH_OK", [], [], {}, False)
    assert b == []


# ================================================================ OSD
def osd(c, cid, i, node="pve1", **q):
    return kill(c, cid, f"nodes/{node}/osds/{i}", f"osd.{i}", **q)


def test_osd_destroy_sends_the_documented_call(api):
    c, cid = api
    r = osd(c, cid, 1)
    assert r.status_code == 202 and r.json() == {"upid": UPID, "node": "pve1"}
    assert dels() == [{"method": "DELETE", "path": "/nodes/pve1/ceph/osd/1", "params": {"cleanup": "0"}, "form": {}}]
    assert audit_pairs(c)[-1] == ("ceph-osd-destroy", "started")


def test_osd_cleanup_is_explicit_and_announced(api):
    c, cid = api
    r = c.delete(u(cid, "nodes/pve1/osds/1"), params={"name": "osd.1", "cleanup": "true"})
    assert r.status_code == 400 and "table de partitions" in r.json()["detail"]
    assert osd(c, cid, 1, cleanup="true").status_code == 202 and dels()[0]["params"] == {"cleanup": "1"}


@pytest.mark.parametrize("osd_id,node,expect", [(0, "pve1", "encore DEDANS"), (4, "pve4", "tourne encore"), (5, "pve4", "encore DEDANS"), (6, "pve5", "illisible")])
def test_osd_refused_when_not_out_and_stopped_and_empty(api, osd_id, node, expect):
    c, cid = api
    r = osd(c, cid, osd_id, node)
    assert r.status_code == 409 and expect in r.json()["detail"] and not dels()


def test_osd_with_placement_groups_is_refused(api):
    c, cid = api
    t = tree()
    t["root"]["children"][0]["children"][1]["pgs"] = 12
    STATE["osd"] = t
    r = osd(c, cid, 1)
    assert r.status_code == 409 and "12 groupe(s)" in r.json()["detail"] and not dels()


@pytest.mark.parametrize("health", ["HEALTH_WARN", "HEALTH_ERR"])
def test_osd_refused_unless_health_ok(api, health):
    c, cid = api
    STATE["health"] = health
    r = osd(c, cid, 1)
    assert r.status_code == 409 and "HEALTH_OK" in r.json()["detail"] and not dels()


def test_osd_refused_while_pgs_are_not_clean(api):
    c, cid = api
    STATE["clean"] = False
    r = osd(c, cid, 1)
    assert r.status_code == 409 and "active+clean" in r.json()["detail"] and not dels()


def test_osd_on_another_host_unknown_or_out_of_range(api):
    c, cid = api
    r = osd(c, cid, 1, "pve2")
    assert r.status_code == 409 and "pve1" in r.json()["detail"]
    assert osd(c, cid, 99).status_code == 404
    assert c.delete(u(cid, "nodes/pve1/osds/-1"), params={"confirm": "true", "name": "osd.-1"}).status_code == 422
    assert c.delete(u(cid, "nodes/pve1/osds/100001"), params={"confirm": "true", "name": "osd.100001"}).status_code == 422
    assert not dels()


def test_osd_node_must_exist_and_be_online(api):
    c, cid = api
    assert osd(c, cid, 1, "pve6").status_code == 404
    assert osd(c, cid, 1, "zzz").status_code == 404
    assert not dels()


def test_osd_needs_confirm_and_name(api):
    c, cid = api
    assert c.delete(u(cid, "nodes/pve1/osds/1"), params={"name": "osd.1"}).status_code == 400
    for bad in ("1", "osd.2", "OSD.1", ""):
        assert kill(c, cid, "nodes/pve1/osds/1", bad).status_code == 400
    assert not dels()


def test_osd_dry_run(api):
    c, cid = api
    j = preview(c, cid, "nodes/pve1/osds/0")
    assert j["expected_name"] == "osd.0" and len(j["blockers"]) == 3 and not dels()           # dedans, en marche ET 40 groupes
    j = preview(c, cid, "nodes/pve1/osds/1", cleanup="true")
    assert j["blockers"] == [] and any("table de partitions" in x for x in j["risks"])


# ================================================================ moniteur
def mon(c, cid, name, node=None, **q):
    return kill(c, cid, f"nodes/{node or name}/monitors/{name}", name, **q)


def test_monitor_destroy_sends_the_documented_call(api):
    c, cid = api
    r = mon(c, cid, "pve4")
    assert r.status_code == 202 and dels() == [{"method": "DELETE", "path": "/nodes/pve4/ceph/mon/pve4", "params": {}, "form": {}}]
    assert audit_pairs(c)[-1] == ("ceph-mon-destroy", "started")


def test_monitor_destroy_needs_confirm_and_name_and_states_the_manager(api):
    c, cid = api
    r = c.delete(u(cid, "nodes/pve4/monitors/pve4"), params={"name": "pve4"})
    assert r.status_code == 400 and "gestionnaire du même nom" in r.json()["detail"]
    assert kill(c, cid, "nodes/pve4/monitors/pve4", "pve3").status_code == 400 and not dels()


def test_last_monitor_is_never_destroyed(api):
    c, cid = api
    STATE["mons"] = STATE["mons"][:1]
    r = mon(c, cid, "pve1")
    assert r.status_code == 409 and "DERNIER moniteur" in r.json()["detail"] and not dels()


def test_monitor_refused_if_quorum_would_be_lost(api):
    c, cid = api
    STATE["mons"][1]["quorum"] = False
    STATE["mons"][2]["quorum"] = False
    r = mon(c, cid, "pve1")                                                          # reste 3 : pve2, pve3 hors quorum, pve4 seul : 1 < 2
    assert r.status_code == 409 and "quorum serait perdu" in r.json()["detail"] and not dels()


def test_monitor_refused_if_quorum_is_unreadable(api):
    c, cid = api
    del STATE["mons"][1]["quorum"]
    r = mon(c, cid, "pve4")
    assert r.status_code == 409 and "illisible" in r.json()["detail"] and not dels()


@pytest.mark.parametrize("health", ["HEALTH_WARN", "HEALTH_ERR"])
def test_monitor_refused_unless_health_ok(api, health):
    c, cid = api
    STATE["health"] = health
    r = mon(c, cid, "pve4")
    assert r.status_code == 409 and "HEALTH_OK" in r.json()["detail"] and not dels()


def test_monitor_risks_leaving_two_or_an_even_number(api):
    c, cid = api
    j = preview(c, cid, "nodes/pve4/monitors/pve4")
    assert j["blockers"] == [] and not any("PAIR" in x or "2 moniteurs" in x for x in j["risks"])            # 4 -> 3 : correct
    STATE["mons"] = STATE["mons"][:3]
    assert any("2 moniteurs" in x for x in preview(c, cid, "nodes/pve3/monitors/pve3")["risks"])
    STATE["mons"] = [dict(m, name=f"m{i}", host=f"pve{i + 1}") for i, m in enumerate(STATE["mons"][:3])] + [dict(STATE["mons"][0], name="m3", host="pve4"), dict(STATE["mons"][0], name="m4", host="pve5")]
    assert any("PAIR" in x for x in preview(c, cid, "nodes/pve1/monitors/m0")["risks"])                    # 5 -> 4


def test_monitor_says_when_its_manager_twin_is_the_last_manager(api):
    c, cid = api
    STATE["mgrs"] = [{"name": "pve4", "host": "pve4", "state": "active"}]
    assert any("DERNIER gestionnaire" in x for x in preview(c, cid, "nodes/pve4/monitors/pve4")["risks"])
    STATE["mgrs"].append({"name": "pve2", "host": "pve2", "state": "standby"})
    assert not any("DERNIER gestionnaire" in x for x in preview(c, cid, "nodes/pve4/monitors/pve4")["risks"])


def test_monitor_other_host_and_unknown(api):
    c, cid = api
    r = kill(c, cid, "nodes/pve2/monitors/pve4", "pve4")
    assert r.status_code == 409 and "pve4" in r.json()["detail"]
    assert kill(c, cid, "nodes/pve1/monitors/zzz", "zzz").status_code == 404
    assert not dels()


# ================================================================ gestionnaire
def test_manager_destroy_and_its_guards(api):
    c, cid = api
    r = kill(c, cid, "nodes/pve2/managers/pve2", "pve2")
    assert r.status_code == 202 and dels() == [{"method": "DELETE", "path": "/nodes/pve2/ceph/mgr/pve2", "params": {}, "form": {}}]
    assert c.delete(u(cid, "nodes/pve3/managers/pve3"), params={"name": "pve3"}).status_code == 400
    assert kill(c, cid, "nodes/pve3/managers/pve3", "pve2").status_code == 400
    assert len(dels()) == 1


def test_manager_refused_when_ceph_is_in_error_but_allowed_in_warning(api):
    c, cid = api
    STATE["health"] = "HEALTH_ERR"
    r = kill(c, cid, "nodes/pve2/managers/pve2", "pve2")
    assert r.status_code == 409 and "HEALTH_ERR" in r.json()["detail"] and not dels()
    STATE["health"] = "HEALTH_WARN"
    assert kill(c, cid, "nodes/pve2/managers/pve2", "pve2").status_code == 202


def test_last_manager_gets_a_stronger_confirmation(api):
    c, cid = api
    STATE["mgrs"] = [{"name": "pve1", "host": "pve1", "state": "active"}]
    r = c.delete(u(cid, "nodes/pve1/managers/pve1"), params={"name": "pve1"})
    assert r.status_code == 400 and "DERNIER gestionnaire" in r.json()["detail"]


def test_manager_unknown_or_on_another_host(api):
    c, cid = api
    assert kill(c, cid, "nodes/pve2/managers/zzz", "zzz").status_code == 404
    assert kill(c, cid, "nodes/pve1/managers/pve2", "pve2").status_code == 409
    assert not dels()


# ================================================================ MDS
def test_mds_destroy_and_its_guards(api):
    c, cid = api
    r = kill(c, cid, "nodes/pve2/mds/pve2", "pve2")
    assert r.status_code == 202 and dels() == [{"method": "DELETE", "path": "/nodes/pve2/ceph/mds/pve2", "params": {}, "form": {}}]
    assert c.delete(u(cid, "nodes/pve1/mds/pve1"), params={"name": "pve1"}).status_code == 400


def test_only_mds_with_a_cephfs_is_refused_even_confirmed(api):
    c, cid = api
    STATE["mds"] = STATE["mds"][:1]
    r = kill(c, cid, "nodes/pve1/mds/pve1", "pve1")
    assert r.status_code == 409 and "SEUL MDS" in r.json()["detail"] and not dels()


def test_only_mds_without_a_cephfs_is_allowed(api):
    c, cid = api
    STATE["mds"] = STATE["mds"][:1]
    STATE["fs"] = []
    assert kill(c, cid, "nodes/pve1/mds/pve1", "pve1").status_code == 202


def test_mds_refused_when_ceph_is_in_error_and_other_active_one_is_enough(api):
    c, cid = api
    STATE["health"] = "HEALTH_ERR"
    assert kill(c, cid, "nodes/pve2/mds/pve2", "pve2").status_code == 409
    STATE["health"] = "HEALTH_OK"
    STATE["mds"] = [{"name": "pve1", "host": "pve1", "state": "up:active"}, {"name": "pve2", "host": "pve2", "state": "down:stopped"}]
    assert kill(c, cid, "nodes/pve1/mds/pve1", "pve1").status_code == 409                              # l'autre ne tourne pas : pas de relais


def test_mds_unknown_or_on_another_host(api):
    c, cid = api
    assert kill(c, cid, "nodes/pve1/mds/zzz", "zzz").status_code == 404
    assert kill(c, cid, "nodes/pve2/mds/pve1", "pve1").status_code == 409


# ================================================================ commun : une écriture à la fois, audit, secrets, accès
def test_only_one_ceph_write_at_a_time(api):
    c, cid = api
    _BUSY.add(cid)
    for p, n in (("pools/other", "other"), ("nodes/pve1/osds/1", "osd.1"), ("nodes/pve4/monitors/pve4", "pve4"), ("nodes/pve2/managers/pve2", "pve2"), ("nodes/pve2/mds/pve2", "pve2")):
        r = kill(c, cid, p, n)
        assert r.status_code == 409 and "déjà en cours" in r.json()["detail"], p
    assert not dels()


def test_the_slot_is_released_after_a_refusal(api):
    c, cid = api
    assert kill(c, cid, "pools/other", "wrong").status_code == 400
    assert cid not in _BUSY
    STATE["storages"] = []
    assert kill(c, cid, "pools/other", "other").status_code == 202 and cid not in _BUSY


def test_every_refusal_and_success_is_audited_without_secret(api):
    c, cid = api
    kill(c, cid, "nodes/pve1/osds/0", "osd.0")                                      # refus (dedans)
    kill(c, cid, "nodes/pve1/osds/1", "osd.1")                                      # succès
    kill(c, cid, "nodes/pve1/osds/1", "mauvais")                                    # nom
    pairs = audit_pairs(c)
    assert pairs.count(("ceph-osd-destroy", "error")) == 2 and pairs.count(("ceph-osd-destroy", "started")) == 1
    text = c.get("/api/audit").text
    assert SECRET not in text and "mauvais" not in text


def test_proxmox_failure_is_a_fixed_message_and_an_error_row(api):
    c, cid = api
    STATE["storages"] = []
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(
        lambda req: _json(403, {"data": None, "message": SECRET}, "Forbidden") if req.method == "DELETE" else _handler(req))))
    r = kill(c, cid, "pools/other", "other")
    assert r.status_code in (403, 502) and SECRET not in r.text and SECRET not in c.get("/api/audit").text
    assert audit_pairs(c)[-1] == ("ceph-pool-destroy", "error")


def test_dry_run_is_never_audited_and_never_deletes(api):
    c, cid = api
    for p in ("pools/other", "nodes/pve1/osds/1", "nodes/pve4/monitors/pve4", "nodes/pve2/managers/pve2", "nodes/pve2/mds/pve2"):
        preview(c, cid, p)
    assert not dels() and not [a for a in audit_pairs(c) if a[0].startswith("ceph-")]


def test_every_route_needs_a_session(client):
    for p in ("pools/other", "nodes/pve1/osds/1", "nodes/pve1/monitors/pve1", "nodes/pve1/managers/pve1", "nodes/pve1/mds/pve1"):
        assert client.delete(u(1, p)).status_code == 401


def test_no_cephfs_destroy_route_exists(api):
    c, cid = api
    for p in ("filesystems/cephfs", "nodes/pve1/fs/cephfs", "fs/cephfs"):
        assert c.delete(u(cid, p), params={"confirm": "true", "name": "cephfs"}).status_code in (404, 405)
    assert not dels()
