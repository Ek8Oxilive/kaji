"""Ceph, ÉCRITURE : moniteurs, gestionnaires, MDS, OSD (lot C3). Faux Proxmox à état : RIEN n'a tourné sur un vrai Ceph.

Chaque garde-fou est testé SÉPARÉMENT (et cassé volontairement : voir la PR). Aucune suppression n'existe dans ce lot.
"""
import copy
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
UPID = "UPID:pve1:0001A2B3:00C4D5E6:67890ABC:cephstop:osd.1:kaji@pve!kaji:"


def _osd(i, up=True, inn=True):
    return {"type": "osd", "id": i, "name": f"osd.{i}", "status": "up" if up else "down", "in": 1 if inn else 0, "device_class": "ssd"}


def tree(**over):
    hosts = {"pve1": [_osd(0), _osd(1)], "pve2": [_osd(2)], "pve3": [_osd(3)]}
    hosts.update(over)
    return {"root": {"type": "root", "name": "default", "children": [{"type": "host", "name": h, "children": o} for h, o in hosts.items()]}}


POOLS = [{"pool_name": "vm-pool", "pool": 2, "type": "replicated", "size": 3, "min_size": 2, "pg_num": 128, "crush_rule_name": "replicated_rule",
          "pg_autoscale_mode": "on", "application_metadata": {"rbd": {}}}]
NODES = [{"node": n, "status": "online"} for n in ("pve1", "pve2", "pve3")] + [{"node": "pve4", "status": "online"}, {"node": "pve5", "status": "offline"}]
MONS = [{"name": n, "host": n, "addr": "10.0.0.1", "rank": i, "quorum": True, "state": "running"} for i, n in enumerate(("pve1", "pve2", "pve3"))]
MGRS = [{"name": "pve1", "host": "pve1", "state": "active"}, {"name": "pve2", "host": "pve2", "state": "standby"}]
MDS = [{"name": "pve1", "host": "pve1", "state": "up:active"}, {"name": "pve2", "host": "pve2", "state": "up:standby"}]
DISKS = [{"devpath": "/dev/sdb", "size": 1000204886016, "model": "ST1000", "used": None}, {"devpath": "/dev/sdc", "size": 1, "model": "X", "used": "LVM"}]
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
        if STATE.get("not_installed") and "ceph" in path:
            return _json(500, {"data": None, "message": "binary not installed: /usr/bin/ceph-mon\n"}, "Internal Server Error")
        if path == "/cluster/ceph/status":
            return _json(200, {"data": {"health": {"status": STATE.get("health", "HEALTH_OK")}}})
        for suffix, key, default in (("/ceph/mon", "mons", MONS), ("/ceph/mgr", "mgrs", MGRS), ("/ceph/mds", "mds", MDS),
                                     ("/ceph/osd", "osd", tree()), ("/ceph/pool", "pools", POOLS), ("/disks/list", "disks", DISKS)):
            if path.endswith(suffix):
                return _json(200, {"data": copy.deepcopy(STATE.get(key, default))})
    if request.method == "POST":
        return _json(200, {"data": UPID})
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


def url(cid, node, tail):
    return f"/api/connections/{cid}/ceph/nodes/{node}/{tail}"


def post(c, cid, node, tail, **body):
    return c.post(url(cid, node, tail), json=body) if body else c.post(url(cid, node, tail))


def detail(r):
    return r.json()["detail"]


def is_confirmation(r):
    return r.status_code == 400 and detail(r).startswith("Confirmation requise (renvoie la requête avec confirm=true) : ")


# ============================== accès, et ce qui n'existe PAS ======================================================

ALL = [("pve1", "monitors"), ("pve1", "managers"), ("pve1", "mds"), ("pve1", "osds"), ("pve1", "osds/1/out"), ("pve1", "osds/1/in"),
       ("pve1", "services/osd/1/start"), ("pve1", "services/osd/1/stop")]


@pytest.mark.parametrize("node,tail", ALL)
def test_requires_auth(client, node, tail):
    assert client.post(url(1, node, tail), json={"dev": "/dev/sdb"}).status_code == 401


@pytest.mark.parametrize("node,tail", ALL)
def test_unknown_connection(api, node, tail):
    c, _ = api
    assert c.post(url(999, node, tail), json={"dev": "/dev/sdb"}).status_code == 404 and CALLS == []


@pytest.mark.parametrize("method", ["delete", "put", "patch", "get"])
@pytest.mark.parametrize("node,tail", ALL + [("pve1", "osds/1"), ("pve1", "monitors/pve1"), ("pve1", "services/osd/1"), ("pve1", "services/osd/1/destroy")])
def test_no_destruction_and_no_other_verb_exists(api, node, tail, method):
    """Le lot C3 ne SUPPRIME rien (c'est le lot C4) : ni DELETE, ni route `destroy`, ni autre verbe."""
    c, cid = api
    assert getattr(c, method)(url(cid, node, tail)).status_code in (404, 405) and CALLS == []


def test_only_get_and_post_are_ever_sent_to_proxmox(api):
    c, cid = api
    post(c, cid, "pve4", "monitors", confirm=True)
    post(c, cid, "pve1", "osds/1/out", confirm=True)
    post(c, cid, "pve1", "services/osd/1/stop", confirm=True)
    assert writes() and all(x["method"] in ("GET", "POST") for x in CALLS)


@pytest.mark.parametrize("node", ["bad node", "-pve", "pve1/../x", "pve1\n", "a" * 70])
def test_invalid_node_is_refused_and_nothing_is_called(api, node):
    c, cid = api
    r = c.post(f"/api/connections/{cid}/ceph/nodes/{quote(node, safe='')}/monitors")
    assert r.status_code in (404, 405, 422) and CALLS == []


@pytest.mark.parametrize("node,tail", [("pve9", "monitors"), ("pve5", "monitors"), ("pve9", "managers"), ("pve5", "mds"), ("pve9", "osds/1/out"),
                                       ("pve5", "services/osd/1/start")])
def test_unknown_or_offline_node_is_404_and_nothing_is_written(api, node, tail):
    c, cid = api
    assert post(c, cid, node, tail).status_code == 404 and writes() == []


@pytest.mark.parametrize("tail", ["services/disk/1/stop", "services/osd/a b/stop", "services/mon/-x/stop", "services/osd/1/restart", "services/osd/1%0A/stop",
                                  "services/osd/" + "1" * 40 + "/stop"])
def test_invalid_service_kind_or_name_is_refused(api, tail):
    c, cid = api
    assert post(c, cid, "pve1", tail).status_code in (404, 405, 422) and writes() == []


@pytest.mark.parametrize("osd", ["-1", "x", "1.5", "100001"])
def test_invalid_osd_id_is_refused(api, osd):
    c, cid = api
    assert post(c, cid, "pve1", f"osds/{osd}/out").status_code == 422 and CALLS == []


@pytest.mark.parametrize("node,tail", ALL)
def test_ceph_not_installed_is_409_and_never_a_write(api, node, tail):
    c, cid = api
    STATE["not_installed"] = True
    r = post(c, cid, node if node != "pve1" else "pve4", tail, dev="/dev/sdb", confirm=True, confirm_dev="/dev/sdb")
    assert r.status_code == 409 and writes() == [] and "binary" not in r.text and "ceph-mon" not in r.text


# ============================== créer : moniteur ===================================================================

def test_create_monitor_on_a_node_without_one(api):
    c, cid = api
    STATE["mons"] = MONS[:2]                              # 2 + 1 = 3 : impair, pas de confirmation
    r = post(c, cid, "pve4", "monitors")
    assert r.status_code == 202 and r.json() == {"upid": UPID, "node": "pve4"}
    assert len(writes()) == 1 and writes()[0]["path"] == "/nodes/pve4/ceph/mon" and writes()[0]["form"] == {}


def test_create_monitor_refused_when_the_node_already_has_one(api):
    c, cid = api
    r = post(c, cid, "pve1", "monitors", confirm=True)
    assert r.status_code == 409 and "déjà un moniteur" in detail(r) and writes() == []


def test_create_monitor_making_an_even_count_needs_confirmation(api):
    c, cid = api
    r = post(c, cid, "pve4", "monitors")                  # 3 + 1 = 4 : pair
    assert is_confirmation(r) and "PAIR" in detail(r) and writes() == []
    assert post(c, cid, "pve4", "monitors", confirm=True).status_code == 202
    assert writes()[0]["form"] == {}                      # confirm n'est jamais transmis


@pytest.mark.parametrize("health", ["HEALTH_ERR", "UNKNOWN", "bizarre"])
def test_create_monitor_refused_when_health_is_error_or_unknown(api, health):
    c, cid = api
    STATE["health"], STATE["mons"] = health, MONS[:2]
    assert post(c, cid, "pve4", "monitors").status_code == 409 and writes() == []


@pytest.mark.parametrize("health", ["HEALTH_OK", "HEALTH_WARN"])
def test_create_monitor_allowed_when_health_is_ok_or_warn(api, health):
    c, cid = api
    STATE["health"], STATE["mons"] = health, MONS[:2]
    assert post(c, cid, "pve4", "monitors").status_code == 202


# ============================== créer : gestionnaire, MDS ==========================================================

def test_create_manager(api):
    c, cid = api
    r = post(c, cid, "pve4", "managers")
    assert r.status_code == 202 and writes()[0]["path"] == "/nodes/pve4/ceph/mgr" and writes()[0]["form"] == {}
    assert post(c, cid, "pve1", "managers").status_code == 409 and len(writes()) == 1


def test_create_mds_and_hot_standby(api):
    c, cid = api
    assert post(c, cid, "pve4", "mds").status_code == 202
    assert writes()[0]["path"] == "/nodes/pve4/ceph/mds" and writes()[0]["form"] == {"hotstandby": "0"}
    CALLS.clear()
    assert post(c, cid, "pve4", "mds", hotstandby=True, evil="x", name="y").status_code == 202
    assert writes()[0]["form"] == {"hotstandby": "1"}     # champs inconnus ignorés
    assert post(c, cid, "pve1", "mds").status_code == 409


@pytest.mark.parametrize("tail", ["managers", "mds"])
@pytest.mark.parametrize("health", ["HEALTH_ERR", "UNKNOWN"])
def test_create_manager_and_mds_refused_when_health_is_error_or_unknown(api, tail, health):
    c, cid = api
    STATE["health"] = health
    assert post(c, cid, "pve4", tail).status_code == 409 and writes() == []


# ============================== créer : OSD (efface le disque) =====================================================

def osd_body(**kw):
    return {"dev": "/dev/sdb", "confirm": True, "confirm_dev": "/dev/sdb", **kw}


def test_create_osd_sends_exact_whitelisted_params(api):
    c, cid = api
    r = c.post(url(cid, "pve4", "osds"), json=osd_body())
    assert r.status_code == 202 and r.json() == {"upid": UPID, "node": "pve4"}
    assert len(writes()) == 1 and writes()[0]["path"] == "/nodes/pve4/ceph/osd" and writes()[0]["form"] == {"dev": "/dev/sdb", "encrypted": "0"}


def test_create_osd_with_every_option_and_unknown_fields_ignored(api):
    c, cid = api
    r = c.post(url(cid, "pve4", "osds"), json=osd_body(encrypted=True, device_class="nvme", db_dev="/dev/sdz", wal_dev="/dev/sdy", force=1))
    assert r.status_code == 202
    assert writes()[0]["form"] == {"dev": "/dev/sdb", "encrypted": "1", "crush-device-class": "nvme"}


@pytest.mark.parametrize("dev", ["sdb", "/dev/", "/dev/../etc/passwd", "/dev/sd b", "/dev/sdb\n", "-rf", "/dev//sdb", "/etc/passwd", "/dev/sdb;ls",
                                 "/dev/sd//b", "/dev/a..b", "/dev/" + "a" * 70, "", " /dev/sdb"])
def test_create_osd_invalid_dev_is_refused_and_nothing_is_called(api, dev):
    c, cid = api
    assert c.post(url(cid, "pve4", "osds"), json=osd_body(dev=dev, confirm_dev=dev)).status_code == 422 and CALLS == []


def test_create_osd_invalid_values_refused(api):
    c, cid = api
    for extra in ({"device_class": "tape"}, {"encrypted": "peut-être"}, {"dev": 12}):
        assert c.post(url(cid, "pve4", "osds"), json=osd_body(**extra)).status_code == 422
    assert CALLS == []


def test_create_osd_invalid_value_is_not_echoed(api):
    c, cid = api
    r = c.post(url(cid, "pve4", "osds"), json=osd_body(dev="/dev/sdb;" + SECRET))
    assert r.status_code == 422 and SECRET not in r.text


def test_create_osd_refused_when_the_disk_is_not_in_the_unused_list(api):
    c, cid = api
    r = c.post(url(cid, "pve4", "osds"), json=osd_body(dev="/dev/sdz", confirm_dev="/dev/sdz"))
    assert r.status_code == 409 and "libre" in detail(r) and writes() == []


def test_create_osd_refused_when_the_disk_is_listed_but_used(api):
    c, cid = api
    r = c.post(url(cid, "pve4", "osds"), json=osd_body(dev="/dev/sdc", confirm_dev="/dev/sdc"))
    assert r.status_code == 409 and writes() == []


def test_create_osd_only_asks_proxmox_for_unused_disks(api):
    c, cid = api
    c.post(url(cid, "pve4", "osds"), json=osd_body())
    assert [x["params"] for x in CALLS if x["path"].endswith("/disks/list")] == [{"type": "unused"}]


def test_create_osd_without_confirmation_says_the_disk_will_be_erased_and_writes_nothing(api):
    c, cid = api
    r = c.post(url(cid, "pve4", "osds"), json={"dev": "/dev/sdb"})
    assert is_confirmation(r) and "EFFACE" in detail(r) and "/dev/sdb" in detail(r) and "ST1000" in detail(r) and "931 Gio" in detail(r)
    assert writes() == []


@pytest.mark.parametrize("typed", [None, "", "/dev/sdc", "/dev/sdb ", "/DEV/SDB", "sdb"])
def test_create_osd_confirmation_needs_the_exact_disk_name_retyped(api, typed):
    c, cid = api
    r = c.post(url(cid, "pve4", "osds"), json={"dev": "/dev/sdb", "confirm": True, "confirm_dev": typed})
    assert r.status_code == 400 and "retapé" in detail(r) and writes() == []


def test_create_osd_retyped_name_alone_is_not_a_confirmation(api):
    c, cid = api
    r = c.post(url(cid, "pve4", "osds"), json={"dev": "/dev/sdb", "confirm_dev": "/dev/sdb"})
    assert is_confirmation(r) and writes() == []


@pytest.mark.parametrize("health", ["HEALTH_ERR", "UNKNOWN"])
def test_create_osd_refused_when_health_is_error_or_unknown(api, health):
    c, cid = api
    STATE["health"] = health
    assert c.post(url(cid, "pve4", "osds"), json=osd_body()).status_code == 409 and writes() == []


def test_create_osd_allowed_in_health_warn(api):
    c, cid = api
    STATE["health"] = "HEALTH_WARN"
    assert c.post(url(cid, "pve4", "osds"), json=osd_body()).status_code == 202


# ============================== OSD : dehors / dedans ==============================================================

def test_osd_out_needs_confirmation_then_sends_one_post_without_it(api):
    c, cid = api
    r = post(c, cid, "pve1", "osds/1/out")
    assert is_confirmation(r) and "DEHORS" in detail(r) and writes() == []
    assert "DÉGRADÉE" not in detail(r)                    # pve1 garde l'OSD 0 : 3 hôtes restent pour size 3
    assert post(c, cid, "pve1", "osds/1/out", confirm=True).status_code == 202
    assert len(writes()) == 1 and writes()[0]["path"] == "/nodes/pve1/ceph/osd/1/out" and writes()[0]["form"] == {}


@pytest.mark.parametrize("health", ["HEALTH_WARN", "HEALTH_ERR", "UNKNOWN"])
def test_osd_out_refused_unless_health_is_ok_even_with_confirmation(api, health):
    c, cid = api
    STATE["health"] = health
    r = post(c, cid, "pve1", "osds/1/out", confirm=True)
    assert r.status_code == 409 and "HEALTH_OK" in detail(r) and writes() == []


def test_osd_out_degrading_redundancy_says_so(api):
    c, cid = api
    r = post(c, cid, "pve3", "osds/3/out")                # seul OSD de pve3 : il reste 2 hôtes pour size 3
    assert is_confirmation(r) and "DÉGRADÉE" in detail(r) and writes() == []
    assert post(c, cid, "pve3", "osds/3/out", confirm=True).status_code == 202


def test_osd_out_refused_even_with_confirmation_when_data_would_become_unavailable(api):
    c, cid = api
    STATE["osd"] = tree(pve3=[])                          # 2 hôtes seulement ; mettre pve2/osd.2 dehors : 1 hôte < min_size 2
    r = post(c, cid, "pve2", "osds/2/out", confirm=True)
    assert r.status_code == 409 and "indisponibles" in detail(r) and writes() == []


def test_osd_out_without_pools_is_not_refused_for_redundancy(api):
    c, cid = api
    STATE["osd"], STATE["pools"] = tree(pve3=[]), []
    assert post(c, cid, "pve2", "osds/2/out", confirm=True).status_code == 202


def test_osd_out_that_is_already_out_or_down_is_not_a_loss(api):
    c, cid = api
    STATE["osd"] = tree(pve1=[_osd(0), _osd(1, up=False)])
    r = post(c, cid, "pve1", "osds/1/out")                # déjà DOWN : aucune capacité perdue de plus
    assert is_confirmation(r) and "DÉGRADÉE" not in detail(r)


def test_osd_out_of_an_osd_already_down_is_not_refused_for_redundancy(api):
    """Cet OSD ne sert déjà plus : le mettre dehors ne retire aucune capacité, même s'il ne reste qu'un hôte utile."""
    c, cid = api
    STATE["osd"] = tree(pve2=[_osd(2, up=False)], pve3=[])
    assert is_confirmation(post(c, cid, "pve2", "osds/2/out")) and post(c, cid, "pve2", "osds/2/out", confirm=True).status_code == 202


def test_osd_out_already_out_is_409(api):
    c, cid = api
    STATE["osd"] = tree(pve1=[_osd(0), _osd(1, inn=False)])
    assert post(c, cid, "pve1", "osds/1/out", confirm=True).status_code == 409 and writes() == []


def test_osd_unknown_is_404_and_wrong_host_is_409(api):
    c, cid = api
    assert post(c, cid, "pve1", "osds/99/out", confirm=True).status_code == 404
    r = post(c, cid, "pve2", "osds/1/out", confirm=True)  # l'OSD 1 est sur pve1
    assert r.status_code == 409 and "pve1" in detail(r) and writes() == []


def test_osd_in_is_not_risky_and_needs_no_confirmation(api):
    c, cid = api
    STATE["osd"] = tree(pve1=[_osd(0), _osd(1, inn=False)])
    r = post(c, cid, "pve1", "osds/1/in")
    assert r.status_code == 202 and writes()[0]["path"] == "/nodes/pve1/ceph/osd/1/in" and writes()[0]["form"] == {}


def test_osd_in_already_in_is_409(api):
    c, cid = api
    assert post(c, cid, "pve1", "osds/1/in").status_code == 409 and writes() == []


@pytest.mark.parametrize("health", ["HEALTH_ERR", "UNKNOWN"])
def test_osd_in_refused_when_health_is_error_or_unknown(api, health):
    c, cid = api
    STATE["osd"], STATE["health"] = tree(pve1=[_osd(0), _osd(1, inn=False)]), health
    assert post(c, cid, "pve1", "osds/1/in").status_code == 409 and writes() == []


# ============================== démarrer un service ================================================================

@pytest.mark.parametrize("kind,name", [("mon", "pve1"), ("mgr", "pve1"), ("mds", "pve1")])
def test_start_service_sends_exact_service_name(api, kind, name):
    c, cid = api
    r = post(c, cid, "pve1", f"services/{kind}/{name}/start")
    assert r.status_code == 202 and writes()[0]["path"] == "/nodes/pve1/ceph/start" and writes()[0]["form"] == {"service": f"{kind}.{name}"}


def test_start_osd_that_is_down(api):
    c, cid = api
    STATE["osd"] = tree(pve2=[_osd(2, up=False)])
    r = post(c, cid, "pve2", "services/osd/2/start")
    assert r.status_code == 202 and writes()[0]["form"] == {"service": "osd.2"}


def test_start_osd_already_up_is_409(api):
    c, cid = api
    assert post(c, cid, "pve2", "services/osd/2/start").status_code == 409 and writes() == []


@pytest.mark.parametrize("health", ["HEALTH_ERR", "HEALTH_WARN", "UNKNOWN"])
def test_start_is_allowed_whatever_the_health_because_it_repairs(api, health):
    c, cid = api
    STATE["health"], STATE["osd"] = health, tree(pve2=[_osd(2, up=False)])
    assert post(c, cid, "pve2", "services/osd/2/start").status_code == 202


@pytest.mark.parametrize("kind,name,node", [("mon", "pve9", "pve1"), ("mgr", "pve9", "pve1"), ("mds", "pve9", "pve1"), ("osd", "99", "pve1"), ("osd", "abc", "pve1"),
                                            ("mon", "pve2", "pve1"), ("mgr", "pve2", "pve1"), ("mds", "pve2", "pve1"), ("osd", "2", "pve1")])
@pytest.mark.parametrize("verb", ["start", "stop"])
def test_service_must_exist_and_run_on_this_node(api, kind, name, node, verb):
    c, cid = api
    r = post(c, cid, node, f"services/{kind}/{name}/{verb}", confirm=True)
    assert r.status_code in (404, 409) and writes() == []


# ============================== arrêter un service =================================================================

def test_stop_osd_needs_confirmation_then_sends_one_post(api):
    c, cid = api
    r = post(c, cid, "pve1", "services/osd/1/stop")
    assert is_confirmation(r) and "ARRÊTÉ" in detail(r) and writes() == []
    assert post(c, cid, "pve1", "services/osd/1/stop", confirm=True).status_code == 202
    assert len(writes()) == 1 and writes()[0]["path"] == "/nodes/pve1/ceph/stop" and writes()[0]["form"] == {"service": "osd.1"}


@pytest.mark.parametrize("health", ["HEALTH_WARN", "HEALTH_ERR", "UNKNOWN"])
@pytest.mark.parametrize("kind,name", [("osd", "1"), ("mon", "pve1"), ("mgr", "pve1"), ("mds", "pve1")])
def test_stop_refused_unless_health_is_ok_even_with_confirmation(api, health, kind, name):
    c, cid = api
    STATE["health"] = health
    r = post(c, cid, "pve1", f"services/{kind}/{name}/stop", confirm=True)
    assert r.status_code == 409 and "HEALTH_OK" in detail(r) and writes() == []


@pytest.mark.parametrize("kind,name", [("osd", "1"), ("mon", "pve1"), ("mgr", "pve1"), ("mds", "pve1")])
def test_stop_always_needs_a_server_side_confirmation(api, kind, name):
    c, cid = api
    r = post(c, cid, "pve1", f"services/{kind}/{name}/stop")
    assert is_confirmation(r) and writes() == []
    assert post(c, cid, "pve1", f"services/{kind}/{name}/stop", confirm=False).status_code == 400 and writes() == []
    assert post(c, cid, "pve1", f"services/{kind}/{name}/stop", confirm=True).status_code == 202


def test_stop_osd_refused_even_with_confirmation_when_data_would_become_unavailable(api):
    c, cid = api
    STATE["osd"] = tree(pve3=[])
    r = post(c, cid, "pve2", "services/osd/2/stop", confirm=True)
    assert r.status_code == 409 and "indisponibles" in detail(r) and writes() == []


def test_stop_osd_degrading_redundancy_says_so(api):
    c, cid = api
    assert "DÉGRADÉE" in detail(post(c, cid, "pve3", "services/osd/3/stop"))


def test_stop_osd_already_down_is_409(api):
    c, cid = api
    STATE["osd"] = tree(pve2=[_osd(2, up=False)])
    assert post(c, cid, "pve2", "services/osd/2/stop", confirm=True).status_code == 409 and writes() == []


def test_stop_monitor_keeps_the_quorum_and_says_how_many_remain(api):
    c, cid = api
    r = post(c, cid, "pve1", "services/mon/pve1/stop")
    assert is_confirmation(r) and "2 sur 3" in detail(r)


def test_stop_monitor_refused_when_the_quorum_would_be_lost(api):
    c, cid = api
    mons = copy.deepcopy(MONS)
    mons[2]["quorum"] = False                              # 2 sur 3 dans le quorum : en retirer un laisse 1 < 2
    STATE["mons"] = mons
    r = post(c, cid, "pve1", "services/mon/pve1/stop", confirm=True)
    assert r.status_code == 409 and "quorum serait perdu" in detail(r) and writes() == []


def test_stop_the_only_monitor_is_refused(api):
    c, cid = api
    STATE["mons"] = MONS[:1]
    assert post(c, cid, "pve1", "services/mon/pve1/stop", confirm=True).status_code == 409 and writes() == []


def test_stop_a_monitor_that_is_already_outside_the_quorum_does_not_lose_it(api):
    c, cid = api
    mons = copy.deepcopy(MONS)
    mons[2]["quorum"] = False
    STATE["mons"] = mons
    assert post(c, cid, "pve3", "services/mon/pve3/stop", confirm=True).status_code == 202


def test_stop_monitor_refused_when_the_quorum_state_is_unreadable(api):
    c, cid = api
    mons = copy.deepcopy(MONS)
    del mons[1]["quorum"]
    STATE["mons"] = mons
    r = post(c, cid, "pve1", "services/mon/pve1/stop", confirm=True)
    assert r.status_code == 409 and "illisible" in detail(r) and writes() == []


def test_stop_manager_says_when_it_is_the_last_one(api):
    c, cid = api
    assert "relais" in detail(post(c, cid, "pve1", "services/mgr/pve1/stop"))
    STATE["mgrs"] = MGRS[:1]
    assert "DERNIER" in detail(post(c, cid, "pve1", "services/mgr/pve1/stop"))


def test_stop_mds_says_when_it_is_the_only_active_one(api):
    c, cid = api
    assert "relais" in detail(post(c, cid, "pve1", "services/mds/pve1/stop"))
    STATE["mds"] = MDS[:1]
    assert "INDISPONIBLE" in detail(post(c, cid, "pve1", "services/mds/pve1/stop"))


# ============================== confirmation : jamais transmise, ne contourne rien ================================

@pytest.mark.parametrize("tail,node", [("services/osd/1/stop", "pve1"), ("osds/1/out", "pve1"), ("monitors", "pve4")])
def test_confirm_is_never_forwarded_to_proxmox(api, tail, node):
    c, cid = api
    post(c, cid, node, tail, confirm=True)
    assert writes() and all("confirm" not in w["form"] and "confirm" not in w["params"] for w in writes())


def test_confirm_string_or_number_is_not_a_confirmation(api):
    c, cid = api
    for v in ("true", "oui", 1, "1"):
        r = c.post(url(cid, "pve1", "services/osd/1/stop"), json={"confirm": v})
        assert r.status_code in (400, 422) and writes() == []


# ============================== une écriture à la fois =============================================================

@pytest.mark.parametrize("node,tail,body", [("pve4", "monitors", {"confirm": True}), ("pve4", "managers", {}), ("pve4", "mds", {}), ("pve4", "osds", osd_body()),
                                            ("pve1", "osds/1/out", {"confirm": True}), ("pve1", "services/osd/1/stop", {"confirm": True}),
                                            ("pve1", "services/osd/1/start", {})])
def test_one_ceph_write_at_a_time(api, node, tail, body):
    c, cid = api
    _BUSY.add(cid)
    r = c.post(url(cid, node, tail), json=body)
    assert r.status_code == 409 and "autre écriture" in detail(r) and CALLS == []


def test_the_slot_is_released_after_success_refusal_and_error(api):
    c, cid = api
    assert post(c, cid, "pve1", "services/osd/1/stop", confirm=True).status_code == 202 and not _BUSY
    assert post(c, cid, "pve1", "services/osd/1/stop").status_code == 400 and not _BUSY
    STATE["fail"] = {"POST /nodes/pve2/ceph/stop": (500, "boom", {"data": None})}
    assert post(c, cid, "pve2", "services/osd/2/stop", confirm=True).status_code in (500, 502) and not _BUSY
    STATE["fail"] = {}
    assert post(c, cid, "pve1", "services/osd/1/stop", confirm=True).status_code == 202


def test_the_write_slot_is_per_connection(api):
    c, cid = api
    _BUSY.add(cid + 1)
    assert post(c, cid, "pve4", "managers").status_code == 202


# ============================== audit ==============================================================================

def test_audit_records_success_every_refusal_and_error(api):
    c, cid = api
    post(c, cid, "pve1", "services/osd/1/stop")                                       # confirmation requise (refus)
    post(c, cid, "pve1", "services/osd/1/stop", confirm=True)                         # succès
    STATE["health"] = "HEALTH_WARN"
    post(c, cid, "pve1", "services/osd/1/stop", confirm=True)                         # santé (refus)
    STATE["health"] = "HEALTH_OK"
    STATE["fail"] = {"POST /nodes/pve2/ceph/stop": (500, "boom", {"data": None})}
    post(c, cid, "pve2", "services/osd/2/stop", confirm=True)                         # erreur Proxmox
    log = audit(c)
    assert [(e["action"], e["status"]) for e in log] == [("ceph-service-stop", "error"), ("ceph-service-stop", "started"),
                                                          ("ceph-service-stop", "error"), ("ceph-service-stop", "error")]
    assert log[1]["upid"] == UPID and "osd.1" in log[1]["detail"] and "Confirmation requise" in log[0]["detail"]
    assert "HEALTH_OK" in log[2]["detail"] and SECRET not in c.get("/api/audit").text


@pytest.mark.parametrize("tail,node,body,action", [("monitors", "pve4", {"confirm": True}, "ceph-mon-create"), ("managers", "pve4", {}, "ceph-mgr-create"),
                                                  ("mds", "pve4", {}, "ceph-mds-create"), ("osds", "pve4", osd_body(), "ceph-osd-create"),
                                                  ("osds/1/out", "pve1", {"confirm": True}, "ceph-osd-out"),
                                                  ("services/osd/1/start", "pve1", {}, "ceph-service-start")])
def test_every_write_kind_is_audited_with_its_own_action_and_the_upid(api, tail, node, body, action):
    c, cid = api
    if tail.endswith("start"):
        STATE["osd"] = tree(pve1=[_osd(0), _osd(1, up=False)])
    r = c.post(url(cid, node, tail), json=body)
    assert r.status_code == 202
    last = audit(c)[-1]
    assert (last["action"], last["status"], last["upid"]) == (action, "started", UPID)


def test_osd_in_is_audited(api):
    c, cid = api
    STATE["osd"] = tree(pve1=[_osd(0), _osd(1, inn=False)])
    post(c, cid, "pve1", "osds/1/in")
    assert audit(c)[-1]["action"] == "ceph-osd-in"


def test_a_ceph_not_installed_refusal_is_audited_without_the_raw_proxmox_text(api):
    c, cid = api
    STATE["not_installed"] = True
    post(c, cid, "pve4", "managers")
    log = audit(c)
    assert log and log[-1]["status"] == "error" and "binary" not in c.get("/api/audit").text


def test_proxmox_error_text_never_reaches_the_user_or_the_audit(api):
    c, cid = api
    STATE["fail"] = {"POST /nodes/pve1/ceph/stop": (500, "boom", {"data": None, "message": f"token {SECRET}"})}
    r = post(c, cid, "pve1", "services/osd/1/stop", confirm=True)
    assert r.status_code in (500, 502) and SECRET not in r.text and SECRET not in c.get("/api/audit").text
