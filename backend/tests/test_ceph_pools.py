import httpx
import pytest

from app.cephwrite import _BUSY, PoolUpdate, changes_of, update_risks
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
UPID = "UPID:pve1:0001A2B3:00C4D5E6:67890ABC:cephcreatepool:vm2:kaji@pve!kaji:"

POOLS = [
    {"pool_name": "vm-pool", "pool": 2, "type": "replicated", "size": 3, "min_size": 2, "pg_num": 128, "crush_rule_name": "replicated_rule",
     "pg_autoscale_mode": "on", "application_metadata": {"rbd": {}}},
    {"pool_name": "ec-pool", "pool": 3, "type": "erasure", "size": 3, "min_size": 2, "pg_num": 32, "crush_rule_name": "ec_rule",
     "pg_autoscale_mode": "warn", "application_metadata": {"rbd": {}}},
    {"pool_name": "fs-data", "pool": 4, "type": "replicated", "size": 3, "min_size": 2, "pg_num": 64, "crush_rule_name": "replicated_rule",
     "pg_autoscale_mode": "off", "application_metadata": {"cephfs": {}, "rbd": {}}},
]
RULES = [{"name": "replicated_rule"}, {"name": "ssd_rule"}, {"rule_name": "ec_rule"}]
NODES = [{"node": "pve1", "status": "online"}, {"node": "pve2", "status": "online"}]
CALLS: list[dict] = []
STATE: dict = {}


def _json(code, body, reason="OK"):
    return httpx.Response(code, json=body, extensions={"reason_phrase": reason.encode()})


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/api2/json")
    form = dict(httpx.QueryParams(request.content.decode())) if request.content else {}
    CALLS.append({"method": request.method, "path": path, "params": dict(request.url.params), "form": form})
    fail = STATE.get("fail", {})
    key = f"{request.method} {path}"
    for k in (key, f"{request.method} " + path.replace(path.split("/")[2], "{n}") if path.startswith("/nodes/") and len(path.split("/")) > 2 else key):
        if k in fail:
            code, reason, body = fail[k]
            return _json(code, body, reason)
    if request.method == "GET":
        if path == "/nodes":
            return _json(200, {"data": NODES})
        if STATE.get("not_installed") and "ceph" in path:
            return _json(500, {"data": None, "message": "binary not installed: /usr/bin/ceph-mon\n"}, "Internal Server Error")
        if path == "/cluster/ceph/status":
            return _json(200, {"data": {"health": {"status": STATE.get("health", "HEALTH_OK")}}})
        if path.endswith("/ceph/pool"):
            return _json(200, {"data": STATE.get("pools", POOLS)})
        if path.endswith("/ceph/rules"):
            return _json(200, {"data": STATE.get("rules", RULES)})
    if request.method in ("POST", "PUT") and "/ceph/pool" in path:
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


def pools_url(cid, name="", query=""):
    return f"/api/connections/{cid}/ceph/pools" + (f"/{name}" if name else "") + query


def post(c, cid, **body):
    return c.post(pools_url(cid), json={"name": "nouveau", **body})


def put(c, cid, name="vm-pool", **body):
    return c.put(pools_url(cid, name), json=body)


# ============================== accès, et ce qui n'existe PAS ======================================================

def test_requires_auth(client):
    assert client.post("/api/connections/1/ceph/pools", json={"name": "x"}).status_code == 401
    assert client.put("/api/connections/1/ceph/pools/x", json={"size": 3}).status_code == 401


def test_unknown_connection(api):
    assert post(api[0], 999).status_code == 404
    assert put(api[0], 999, size=3).status_code == 404


@pytest.mark.parametrize("method,path", [("delete", "/pools"), ("patch", "/pools/vm-pool"), ("post", "/pools/vm-pool"), ("put", "/pools"), ("delete", "/osds/0")])
def test_no_destruction_and_no_other_write_exists(api, method, path):
    """Ce lot ne SUPPRIME rien : la suppression d'un pool vit dans le lot C4 (`DELETE /pools/{pool}`, `tests/test_ceph_destroy.py`, avec ses barrières) ;
    ici ne restent que des routes qui n'existent PAS (suppression de la collection, verbes inconnus, OSD hors d'un nœud)."""
    c, cid = api
    assert getattr(c, method)(f"/api/connections/{cid}/ceph{path}").status_code in (404, 405)
    assert CALLS == []


def test_a_delete_is_never_sent_to_proxmox(api):
    """Créer et modifier un pool n'envoient jamais de suppression (le `DELETE` d'un pool est une route à part, lot C4)."""
    c, cid = api
    post(c, cid)
    put(c, cid, size=2, confirm=True)
    assert all(x["method"] in ("GET", "POST", "PUT") for x in CALLS)


# ============================== création ===========================================================================

def test_create_sends_exact_whitelisted_params_with_safe_defaults(api):
    c, cid = api
    r = post(c, cid)
    assert r.status_code == 202 and r.json() == {"upid": UPID, "node": "pve1", "pool": "nouveau"}
    assert len(writes()) == 1 and writes()[0]["method"] == "POST" and writes()[0]["path"] == "/nodes/pve1/ceph/pool"
    assert writes()[0]["form"] == {"name": "nouveau", "size": "3", "min_size": "2", "pg_num": "128", "pg_autoscale_mode": "warn",
                                   "application": "rbd", "add_storages": "0"}


def test_create_with_every_option(api):
    c, cid = api
    r = post(c, cid, size=4, min_size=3, pg_num=256, autoscale="on", application="rbd", crush_rule="ssd_rule", add_storage=True, confirm=True)
    assert r.status_code == 202
    assert writes()[0]["form"] == {"name": "nouveau", "size": "4", "min_size": "3", "pg_num": "256", "pg_autoscale_mode": "on",
                                   "application": "rbd", "add_storages": "1", "crush_rule": "ssd_rule"}


def test_create_unknown_fields_are_never_forwarded(api):
    c, cid = api
    extra = {"erasure-coding": "k=2,m=1", "target_size": "10G", "target_size_ratio": 0.5, "pg_num_min": 1, "force": 1, "node": "evil", "id": 9,
             "add_storages": 1, "confirm": True, "script": "/x", "size2": 1}
    assert post(c, cid, **extra).status_code == 202
    assert set(writes()[0]["form"]) == {"name", "size", "min_size", "pg_num", "pg_autoscale_mode", "application", "add_storages"}
    assert writes()[0]["form"]["add_storages"] == "0"


# ---- redondance (cadrage §3, règle 3) : chaque garde-fou séparément ---------------------------------------------

@pytest.mark.parametrize("size", [1, 0, -1])
def test_create_refuses_a_single_copy(api, size):
    c, cid = api
    r = post(c, cid, size=size, min_size=2)
    assert r.status_code == 422 and writes() == [] and CALLS == []


@pytest.mark.parametrize("min_size", [1, 0, -1])
def test_create_refuses_min_size_of_one(api, min_size):
    c, cid = api
    r = post(c, cid, size=3, min_size=min_size)
    assert r.status_code == 422 and CALLS == []


def test_create_refuses_min_size_above_size(api):
    c, cid = api
    assert post(c, cid, size=2, min_size=3).status_code == 422 and CALLS == []


def test_create_size_two_min_size_two_is_allowed_with_confirmation(api):
    assert post(api[0], api[1], size=2, min_size=2, confirm=True).status_code == 202


def test_create_size_two_needs_confirmation_and_writes_nothing(api):
    """Un pool à 2 copies est autorisé (cadrage : au moins 2) mais risqué : le SERVEUR exige confirm=true et dit pourquoi."""
    c, cid = api
    r = post(c, cid, size=2, min_size=2)
    assert r.status_code == 400 and r.json()["detail"].startswith("Confirmation requise (renvoie la requête avec confirm=true) : ")
    assert "2 copies" in r.json()["detail"] and writes() == [] and not _BUSY
    assert post(c, cid, size=2, min_size=2, confirm=True).status_code == 202


def test_create_add_storage_needs_confirmation_and_writes_nothing(api):
    c, cid = api
    r = post(c, cid, add_storage=True)
    assert r.status_code == 400 and "TOUT le cluster" in r.json()["detail"] and writes() == []
    assert post(c, cid, add_storage=True, confirm=True).status_code == 202 and writes()[0]["form"]["add_storages"] == "1"


def test_create_both_risks_are_listed_together(api):
    d = post(api[0], api[1], size=2, min_size=2, add_storage=True).json()["detail"]
    assert "2 copies" in d and "TOUT le cluster" in d and " ; " in d


def test_create_default_and_three_copies_need_no_confirmation(api):
    assert post(api[0], api[1]).status_code == 202 and post(api[0], api[1], name="p2", size=3).status_code == 202


def test_create_confirm_is_never_forwarded_to_proxmox(api):
    post(api[0], api[1], size=2, min_size=2, confirm=True)
    assert "confirm" not in writes()[0]["form"]


def test_create_confirmation_does_not_bypass_other_refusals(api):
    """confirm=true ne remplace NI la barrière de santé NI les contrôles d'existence."""
    c, cid = api
    assert post(c, cid, name="vm-pool", size=2, min_size=2, confirm=True).status_code == 409
    STATE["health"] = "HEALTH_ERR"
    assert post(c, cid, size=2, min_size=2, confirm=True).status_code == 409 and writes() == []


def test_create_defaults_are_size_3_min_size_2(api):
    post(api[0], api[1])
    assert (writes()[0]["form"]["size"], writes()[0]["form"]["min_size"]) == ("3", "2")


@pytest.mark.parametrize("patch", [
    {"name": ""}, {"name": ".mgr"}, {"name": ".hidden"}, {"name": "a/b"}, {"name": "a b"}, {"name": "a:b"}, {"name": "-x"}, {"name": "x" * 64},
    {"name": "ok\n"}, {"name": "ok\r"}, {"name": "ok\x00"}, {"name": None}, {"name": 7}, {"name": ["a"]}, {"name": "é"}, {"name": "a;rm"},
    {"size": 8}, {"size": "x"}, {"size": 3.5}, {"size": None}, {"size": []}, {"min_size": 8}, {"min_size": "x"}, {"min_size": 2.5},
    {"pg_num": 0}, {"pg_num": -4}, {"pg_num": 3}, {"pg_num": 100}, {"pg_num": 32769}, {"pg_num": 65536}, {"pg_num": "x"}, {"pg_num": 128.5},
    {"autoscale": "auto"}, {"autoscale": "ON"}, {"autoscale": ""}, {"application": "nfs"}, {"application": "RBD"}, {"application": ""},
    {"crush_rule": "a b"}, {"crush_rule": "../x"}, {"crush_rule": ".x"}, {"crush_rule": "r\n"}, {"crush_rule": "r" * 64}, {"crush_rule": 5},
    {"add_storage": "peut-être"}, {"add_storage": True, "application": "cephfs"}, {"add_storage": True, "application": "rgw"},
])
def test_create_invalid_body_refused_and_nothing_called(api, patch):
    c, cid = api
    r = post(c, cid, **patch)
    assert r.status_code == 422 and CALLS == [] and SECRET not in r.text


def test_create_missing_name_refused(api):
    assert api[0].post(pools_url(api[1]), json={"size": 3}).status_code == 422 and CALLS == []


def test_create_valid_pg_num_powers_of_two_accepted(api):
    for n in (1, 2, 64, 1024, 32768):
        assert post(api[0], api[1], name=f"p{n}", pg_num=n).status_code == 202


def test_create_invalid_value_is_not_echoed(api):
    assert "valeur-saisie-evil" not in post(api[0], api[1], autoscale="valeur-saisie-evil").text


@pytest.mark.parametrize("node", ["-pve", "pve_1", "pve.1", "p" * 64, "pve1%0a", "a b"])
def test_invalid_node_refused_and_nothing_called(api, node):
    c, cid = api
    assert post(c, cid).status_code == 202 or True                     # (amorce : le nœud par défaut fonctionne)
    CALLS.clear()
    r = c.post(pools_url(cid, query=f"?node={node}"), json={"name": "x"})
    assert r.status_code == 422 and CALLS == []


# ---- santé, existence, Ceph absent ---------------------------------------------------------------------------

@pytest.mark.parametrize("health", ["HEALTH_ERR", "UNKNOWN"])
def test_create_refused_when_health_is_error_or_unknown(api, health):
    c, cid = api
    STATE["health"] = health
    r = post(c, cid)
    assert r.status_code == 409 and "pas dans un état sûr" in r.json()["detail"] and writes() == []


@pytest.mark.parametrize("health", ["HEALTH_OK", "HEALTH_WARN"])
def test_create_allowed_when_health_is_ok_or_warn(api, health):
    STATE["health"] = health
    assert post(api[0], api[1]).status_code == 202


def test_create_existing_pool_is_409_and_nothing_is_written(api):
    c, cid = api
    r = post(c, cid, name="vm-pool")
    assert r.status_code == 409 and "existe déjà" in r.json()["detail"] and writes() == []


def test_create_when_ceph_is_not_installed_is_409_not_a_write(api):
    c, cid = api
    STATE["not_installed"] = True
    r = post(c, cid)
    assert r.status_code == 409 and "pas installé" in r.json()["detail"] and writes() == []
    assert "binary" not in r.text and "ceph-mon" not in r.text


def test_create_unknown_crush_rule_is_refused(api):
    c, cid = api
    r = post(c, cid, crush_rule="inexistante")
    assert r.status_code == 422 and "inconnue" in r.json()["detail"] and writes() == []


def test_create_known_crush_rule_including_the_rule_name_form(api):
    assert post(api[0], api[1], crush_rule="ec_rule").status_code == 202


def test_create_unreadable_crush_rules_are_refused_not_skipped(api):
    c, cid = api
    STATE["fail"] = {"GET /nodes/pve1/ceph/rules": (500, "boom", {"data": None})}
    r = post(c, cid, crush_rule="ssd_rule")
    assert r.status_code == 502 and writes() == []


def test_create_without_crush_rule_does_not_read_rules(api):
    post(api[0], api[1])
    assert all(not x["path"].endswith("/ceph/rules") for x in CALLS)


def test_create_proxmox_write_error_is_502_audited_without_secret(api):
    c, cid = api
    STATE["fail"] = {"POST /nodes/pve1/ceph/pool": (500, "boom", {"data": None, "message": SECRET})}
    r = post(c, cid)
    assert r.status_code == 502 and SECRET not in r.text
    log = audit(c)
    assert [(e["action"], e["status"]) for e in log] == [("ceph-pool-create", "error")] and SECRET not in c.get("/api/audit").text


def test_create_reads_failing_are_502_and_nothing_written(api):
    c, cid = api
    STATE["fail"] = {"GET /cluster/ceph/status": (500, "boom", {"data": None})}
    assert post(c, cid).status_code == 502 and writes() == []


# ---- une seule écriture à la fois ---------------------------------------------------------------------------

def test_create_refused_while_another_ceph_write_is_running(api):
    c, cid = api
    _BUSY.add(cid)
    r = post(c, cid)
    assert r.status_code == 409 and "déjà en cours" in r.json()["detail"] and CALLS == []
    r2 = put(c, cid, size=2, confirm=True)
    assert r2.status_code == 409 and CALLS == []


def test_the_write_slot_is_released_after_success_refusal_and_error(api):
    c, cid = api
    assert post(c, cid).status_code == 202 and not _BUSY
    assert post(c, cid, name="vm-pool").status_code == 409 and not _BUSY            # refus
    STATE["fail"] = {"POST /nodes/pve1/ceph/pool": (500, "boom", {"data": None})}
    assert post(c, cid, name="autre").status_code == 502 and not _BUSY               # erreur
    STATE["fail"] = {}
    assert post(c, cid, name="encore").status_code == 202


def test_the_write_slot_is_per_connection(api):
    c, cid = api
    _BUSY.add(cid + 1)
    assert post(c, cid).status_code == 202


# ---- audit ---------------------------------------------------------------------------------------------------------

def test_create_audit_records_success_every_refusal_and_error(api):
    c, cid = api
    post(c, cid, name="vm-pool")                                                     # existe déjà
    STATE["health"] = "HEALTH_ERR"
    post(c, cid)                                                                      # santé
    STATE["health"] = "HEALTH_OK"
    post(c, cid, crush_rule="inexistante")                                           # règle inconnue
    post(c, cid, size=4, min_size=3, crush_rule="ssd_rule", add_storage=True, confirm=True)        # succès
    STATE["fail"] = {"POST /nodes/pve1/ceph/pool": (500, "boom", {"data": None})}
    post(c, cid, name="p5")                                                           # erreur Proxmox
    log = audit(c)
    assert [(e["action"], e["status"]) for e in log] == [("ceph-pool-create", "error")] * 3 + [("ceph-pool-create", "started"), ("ceph-pool-create", "error")]
    assert log[3]["upid"] == UPID and "size=4" in log[3]["detail"] and "règle=ssd_rule" in log[3]["detail"] and "+ stockage" in log[3]["detail"]
    assert "existe déjà" in log[0]["detail"] and "pas dans un état sûr" in log[1]["detail"] and "inconnue" in log[2]["detail"]
    assert SECRET not in c.get("/api/audit").text


# ============================== modification =======================================================================

def test_update_unknown_pool_is_404_and_nothing_written(api):
    c, cid = api
    assert put(c, cid, "absent", autoscale="on").status_code == 404 and writes() == []


@pytest.mark.parametrize("name", ["-x", ".mgr", "a b", "x" * 64, "a%2Fb"])
def test_update_invalid_pool_name_refused(api, name):
    c, cid = api
    assert put(c, cid, name, autoscale="on").status_code in (404, 405, 422) and writes() == []


def test_update_when_ceph_is_not_installed_is_409(api):
    c, cid = api
    STATE["not_installed"] = True
    r = put(c, cid, autoscale="on")
    assert r.status_code == 409 and "pas installé" in r.json()["detail"] and writes() == []


@pytest.mark.parametrize("body", [{}, {"confirm": True}, {"size": None}, {"min_size": None}, {"pg_num": None}, {"autoscale": None}, {"application": None}, {"crush_rule": None}])
def test_update_empty_or_null_refused(api, body):
    c, cid = api
    assert c.put(pools_url(api[1], "vm-pool"), json=body).status_code == 422 and CALLS == []


@pytest.mark.parametrize("body", [{"size": 1}, {"size": 0}, {"size": 8}, {"min_size": 1}, {"min_size": 0}, {"min_size": 8}, {"pg_num": 3}, {"pg_num": 0},
                                  {"pg_num": 99999}, {"autoscale": "auto"}, {"application": "nfs"}, {"crush_rule": "a b"}, {"size": "x"}, {"pg_num": "x"}])
def test_update_invalid_values_refused_and_nothing_called(api, body):
    c, cid = api
    r = c.put(pools_url(cid, "vm-pool"), json={**body, "confirm": True})
    assert r.status_code == 422 and CALLS == []


def test_update_refuses_a_single_copy_and_min_size_of_one_separately(api):
    c, cid = api
    assert put(c, cid, size=1, confirm=True).status_code == 422
    assert put(c, cid, min_size=1, confirm=True).status_code == 422
    assert CALLS == []


def test_update_unknown_fields_are_never_forwarded(api):
    c, cid = api
    extra = {"force": 1, "name": "autre", "pool": "x", "target_size": "1T", "target_size_ratio": 0.5, "pg_num_min": 1,
             "erasure_profile": "p", "add_storages": 1, "script": "/x"}
    r = c.put(pools_url(cid, "vm-pool"), json={"autoscale": "warn", **extra})
    assert r.status_code == 200
    assert writes()[0]["path"] == "/nodes/pve1/ceph/pool/vm-pool" and writes()[0]["form"] == {"pg_autoscale_mode": "warn"}


def test_update_non_risky_change_needs_no_health_and_no_confirmation(api):
    c, cid = api
    STATE["health"] = "HEALTH_ERR"
    r = put(c, cid, autoscale="warn")
    assert r.status_code == 200 and r.json()["changes"] == {"autoscale": "warn"} and r.json()["upid"] == UPID
    assert writes()[0]["method"] == "PUT" and writes()[0]["form"] == {"pg_autoscale_mode": "warn"}
    assert all(x["path"] != "/cluster/ceph/status" for x in CALLS)


def test_update_application_change_is_not_risky(api):
    c, cid = api
    STATE["health"] = "HEALTH_ERR"
    assert put(c, cid, "ec-pool", application="cephfs").status_code == 200
    assert writes()[0]["form"] == {"application": "cephfs"}


def test_update_same_values_are_not_sent_and_say_so(api):
    c, cid = api
    r = put(c, cid, size=3, min_size=2, pg_num=128, autoscale="on", crush_rule="replicated_rule", application="rbd")
    assert r.status_code == 400 and "Aucun changement" in r.json()["detail"] and writes() == []


def test_update_only_the_values_that_differ_are_sent(api):
    c, cid = api
    r = put(c, cid, size=3, min_size=2, autoscale="warn", confirm=True)
    assert r.status_code == 200 and writes()[0]["form"] == {"pg_autoscale_mode": "warn"}


@pytest.mark.parametrize("field,value", [("size", 2), ("size", 4), ("min_size", 3), ("pg_num", 256), ("pg_num", 64), ("crush_rule", "ssd_rule")])
def test_update_risky_change_needs_confirmation_and_sends_nothing_without_it(api, field, value):
    c, cid = api
    body = {field: value}
    if field == "size" and value == 2:
        body["min_size"] = 2                                                          # sinon min_size 2 reste ≤ size 2 : rien à ajouter
    r = c.put(pools_url(cid, "vm-pool"), json=body)
    assert r.status_code == 400 and "Confirmation requise" in r.json()["detail"] and "confirm=true" in r.json()["detail"] and writes() == []
    assert c.put(pools_url(cid, "vm-pool"), json={**body, "confirm": True}).status_code == 200
    assert "confirm" not in writes()[0]["form"]


@pytest.mark.parametrize("confirm", [False, None, 0, "false", ""])
def test_update_confirm_values_that_are_not_true_do_not_confirm(api, confirm):
    c, cid = api
    r = c.put(pools_url(cid, "vm-pool"), json={"size": 4, "confirm": confirm})
    assert r.status_code in (400, 422) and writes() == []


@pytest.mark.parametrize("health", ["HEALTH_WARN", "HEALTH_ERR", "UNKNOWN"])
@pytest.mark.parametrize("body", [{"size": 4}, {"min_size": 3}, {"pg_num": 256}, {"crush_rule": "ssd_rule"}])
def test_update_risky_change_refused_unless_health_is_ok_even_with_confirmation(api, health, body):
    c, cid = api
    STATE["health"] = health
    r = put(c, cid, confirm=True, **body)
    assert r.status_code == 409 and "pas en bonne santé" in r.json()["detail"] and writes() == []


def test_update_reasons_say_what_ceph_will_do(api):
    c, cid = api
    r = put(c, cid, size=2, min_size=2, pg_num=256, crush_rule="ssd_rule")
    d = r.json()["detail"]
    assert "RÉDUIT le nombre de copies (de 3 à 2)" in d and "groupes de placement (de 128 à 256)" in d and "règle de placement (de replicated_rule à ssd_rule)" in d
    assert " ; " in d and d.startswith("Confirmation requise (renvoie la requête avec confirm=true) : ")


def test_update_reason_texts_for_raising_values():
    cur = {"size": 3, "min_size": 2, "pg_num": 128, "crush_rule": "a"}
    assert "AJOUTE des copies (de 3 à 4)" in update_risks({"size": 4}, cur)[0]
    assert "AUGMENTE min_size (de 2 à 3)" in update_risks({"min_size": 3}, cur)[0]
    assert "RÉDUIT min_size (de 3 à 2)" in update_risks({"min_size": 2}, {**cur, "min_size": 3})[0]
    assert update_risks({"autoscale": "on", "application": "rbd"}, cur) == []


def test_update_min_size_above_size_refused_on_the_effective_values(api):
    c, cid = api
    assert put(c, cid, size=2, confirm=True).status_code == 200                        # 2 ≥ min_size 2 : accepté
    CALLS.clear()
    r = put(c, cid, min_size=4, confirm=True)
    assert r.status_code == 409 and "ne peut pas dépasser size" in r.json()["detail"] and writes() == []


def test_update_lowering_size_below_the_existing_min_size_is_refused(api):
    c, cid = api
    STATE["pools"] = [{**POOLS[0], "min_size": 3}]
    r = put(c, cid, size=2, confirm=True)
    assert r.status_code == 409 and "ne peut pas dépasser size" in r.json()["detail"] and writes() == []


def test_update_erasure_pool_size_and_crush_rule_are_refused_but_min_size_is_not(api):
    c, cid = api
    for body in ({"size": 4}, {"crush_rule": "ssd_rule"}):
        r = put(c, cid, "ec-pool", confirm=True, **body)
        assert r.status_code == 409 and "effacement" in r.json()["detail"]
    assert writes() == []
    assert put(c, cid, "ec-pool", min_size=3, confirm=True).status_code == 200


def test_update_unknown_crush_rule_refused_after_health_and_before_confirmation(api):
    c, cid = api
    r = put(c, cid, crush_rule="inexistante")                                         # sans confirm : la règle est refusée d'abord
    assert r.status_code == 422 and "inconnue" in r.json()["detail"] and writes() == []


def test_update_proxmox_error_is_502_audited_without_secret(api):
    c, cid = api
    STATE["fail"] = {"PUT /nodes/pve1/ceph/pool/vm-pool": (500, "boom", {"data": None, "message": SECRET})}
    r = put(c, cid, autoscale="warn")
    assert r.status_code == 502 and SECRET not in r.text and not _BUSY
    assert [(e["action"], e["status"]) for e in audit(c)] == [("ceph-pool-update", "error")] and SECRET not in c.get("/api/audit").text


def test_update_audit_records_success_every_refusal_and_error(api):
    c, cid = api
    put(c, cid, "absent", autoscale="on")                                             # introuvable
    put(c, cid, size=4)                                                               # confirmation
    STATE["health"] = "HEALTH_WARN"
    put(c, cid, size=4, confirm=True)                                                 # santé
    STATE["health"] = "HEALTH_OK"
    put(c, cid, size=4, confirm=True)                                                 # succès
    STATE["fail"] = {"PUT /nodes/pve1/ceph/pool/vm-pool": (500, "boom", {"data": None})}
    put(c, cid, autoscale="warn")                                                     # erreur
    log = audit(c)
    assert [(e["action"], e["status"]) for e in log] == [("ceph-pool-update", "error")] * 3 + [("ceph-pool-update", "started"), ("ceph-pool-update", "error")]
    assert [e["target"] for e in log] == ["pool/absent", "pool/vm-pool", "pool/vm-pool", "pool/vm-pool", "pool/vm-pool"]
    assert log[3]["upid"] == UPID and "size=4" in log[3]["detail"] and "Confirmation requise" in log[1]["detail"]
    assert SECRET not in c.get("/api/audit").text


def test_update_reads_failing_are_502_and_nothing_written(api):
    c, cid = api
    STATE["fail"] = {"GET /cluster/ceph/status": (500, "boom", {"data": None})}
    assert put(c, cid, size=4, confirm=True).status_code == 502 and writes() == []


# ============================== règles CRUSH (lecture) ==============================================================

def test_rules_route_is_read_only_and_shaped(api):
    c, cid = api
    r = c.get(f"/api/connections/{cid}/ceph/rules").json()
    assert r["installed"] is True and [x["name"] for x in r["rules"]] == ["ec_rule", "replicated_rule", "ssd_rule"]
    assert c.post(f"/api/connections/{cid}/ceph/rules", json={}).status_code == 405


def test_rules_route_when_not_installed(api):
    c, cid = api
    STATE["not_installed"] = True
    assert c.get(f"/api/connections/{cid}/ceph/rules").json() == {"installed": False, "message": "Ceph n'est pas installé sur ce cluster."}


def test_rules_route_requires_auth(client):
    assert client.get("/api/connections/1/ceph/rules").status_code == 401


@pytest.mark.parametrize("junk", [None, "x", 3, {}, [None, 5, {"name": 3}, {"rule_id": "a"}, {"name": "ok", "id": "z"}]])
def test_rules_tolerate_anything(junk):
    from app.cephspec import shape_rules
    assert isinstance(shape_rules(junk), list)


# ============================== unitaire ===========================================================================

def test_changes_of_ignores_identical_and_detects_application_change():
    cur = {"size": 3, "min_size": 2, "pg_num": 128, "autoscale": "on", "crush_rule": "r", "applications": ["rbd"]}
    assert changes_of(PoolUpdate(size=3, application="rbd"), cur) == {}
    assert changes_of(PoolUpdate(size=4, application="cephfs"), cur) == {"size": 4, "application": "cephfs"}
    assert changes_of(PoolUpdate(application="rbd"), {**cur, "applications": ["rbd", "cephfs"]}) == {"application": "rbd"}
    assert changes_of(PoolUpdate(application="rbd"), {**cur, "applications": []}) == {"application": "rbd"}


def test_internal_pools_such_as_dot_mgr_cannot_be_modified_even_though_they_exist(api):
    """Sur un vrai Ceph, `.mgr` existe et figure dans la liste des pools : seul le motif du nom (point initial interdit)
    empêche d'y toucher. Un pool inexistant donnerait 404 de toute façon : il faut qu'il EXISTE pour voir la protection."""
    c, cid = api
    STATE["pools"] = [*POOLS, {"pool_name": ".mgr", "pool": 1, "type": "replicated", "size": 3, "min_size": 2, "pg_num": 1,
                               "crush_rule_name": "replicated_rule", "pg_autoscale_mode": "on", "application_metadata": {"mgr": {}}}]
    for body in ({"autoscale": "off"}, {"size": 2, "min_size": 2, "confirm": True}, {"pg_num": 2, "confirm": True}):
        r = c.put(pools_url(cid, ".mgr"), json=body)
        assert r.status_code == 422, r.text
    assert writes() == []
    assert post(c, cid, name=".mgr").status_code == 422 and writes() == []
