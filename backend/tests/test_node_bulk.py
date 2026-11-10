"""Actions groupées d'un nœud et Wake-on-LAN (lot #230) : faux Proxmox STRICT (méthode, chemin et paramètres exacts, 400 sinon).

Les noms de paramètres (`vms`, `force`, `force-stop`, `timeout`, `target`, `maxworkers`, `with-local-disks`) sont ceux du schéma Proxmox VE ;
ils restent À CONFIRMER contre le vrai cluster (voir le compte rendu de la PR).
"""
import httpx
import pytest
from urllib.parse import parse_qs

from app.config import get_settings
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
UPID = "UPID:enzo:0001A2B3:00C4D5E6:67890ABC:startall::kaji@pve!kaji:"
SCHEMA = {  # chemin -> paramètres POST autorisés
    "/nodes/enzo/startall": {"vms", "force"},
    "/nodes/enzo/stopall": {"vms", "force-stop", "timeout"},
    "/nodes/enzo/migrateall": {"vms", "target", "maxworkers", "with-local-disks"},
    "/nodes/enzo2/wakeonlan": set(),
}
REQUIRED = {"/nodes/enzo/startall": {"vms"}, "/nodes/enzo/stopall": {"vms"}, "/nodes/enzo/migrateall": {"vms", "target"}, "/nodes/enzo2/wakeonlan": set()}
CALLS: list[tuple[str, str, dict]] = []
ST: dict = {}


def cluster(nodes, quorate=True):
    return [{"type": "cluster", "name": "c", "quorate": 1 if quorate else 0}] + [{"type": "node", "name": n, "online": 1 if on else 0, "ip": "1.1.1.1"} for n, on in nodes]


def guest(vmid, node="enzo", status="running", template=0, gtype="qemu"):
    return {"type": gtype, "vmid": vmid, "name": f"vm{vmid}", "node": node, "status": status, "template": template}


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
    CALLS.append((request.method, p, form))
    if p == "/cluster/status":
        return httpx.Response(200, json={"data": ST["cluster"]})
    if p == "/cluster/resources":
        return httpx.Response(200, json={"data": ST["guests"]})
    if request.method == "POST" and p in SCHEMA:
        if set(form) - SCHEMA[p] or not set(form) >= REQUIRED[p]:
            return httpx.Response(400, json={"data": None, "message": "paramètre inconnu ou manquant"})
        if ST.get("write_fail"):
            return httpx.Response(403, json={"data": None, "message": SECRET})
        return httpx.Response(200, json={"data": UPID})
    return httpx.Response(404, json={"data": None})


@pytest.fixture
def api(client, monkeypatch):
    monkeypatch.delenv("KAJI_PROTECTED_VMIDS", raising=False)
    get_settings.cache_clear()
    CALLS.clear()
    ST.clear()
    ST.update(cluster=cluster([("enzo", True), ("enzo2", True)]), guests=[])
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()
    monkeypatch.undo()
    get_settings.cache_clear()


def bulk(c, cid, action, vmids, node="enzo", **b):
    return c.post(f"/api/connections/{cid}/nodes/{node}/bulk", json={"action": action, "vmids": vmids, "confirm": True, "type_name": node, **b})


def writes():
    return [x for x in CALLS if x[0] == "POST"]


@pytest.fixture
def protected_105(monkeypatch):
    monkeypatch.setenv("KAJI_PROTECTED_VMIDS", "105,116")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


# --- startall -------------------------------------------------------------------------------------------------------------------------------------------

def test_startall_sends_only_stopped_listed_machines_with_force(api):
    c, cid = api
    ST["guests"] = [guest(100, status="stopped"), guest(101, status="stopped"), guest(102), guest(103, status="stopped")]
    r = bulk(c, cid, "startall", [100, 101, 102], confirm=True, type_name=None)
    assert r.status_code == 200 and r.json() == {"node": "enzo", "action": "startall", "upid": UPID, "vmids": [100, 101]}
    assert writes() == [("POST", "/nodes/enzo/startall", {"vms": "100,101", "force": "1"})]   # 103 non listée : jamais envoyée ; 102 déjà en marche


def test_startall_needs_confirm_but_not_the_node_name(api):
    c, cid = api
    ST["guests"] = [guest(100, status="stopped")]
    assert bulk(c, cid, "startall", [100], confirm=False).status_code == 400
    assert not writes()
    assert bulk(c, cid, "startall", [100], type_name=None).status_code == 200


def test_startall_nothing_to_start_is_a_409(api):
    c, cid = api
    ST["guests"] = [guest(100)]
    r = bulk(c, cid, "startall", [100])
    assert r.status_code == 409 and not writes()


# --- stopall --------------------------------------------------------------------------------------------------------------------------------------------

def test_stopall_sends_running_machines_with_explicit_force_stop_and_timeout(api):
    c, cid = api
    ST["guests"] = [guest(100), guest(101, status="stopped"), guest(102, gtype="lxc")]
    r = bulk(c, cid, "stopall", [100, 101, 102])
    assert r.status_code == 200 and r.json()["vmids"] == [100, 102]
    assert writes() == [("POST", "/nodes/enzo/stopall", {"vms": "100,102", "force-stop": "0", "timeout": "180"})]
    CALLS.clear()
    assert bulk(c, cid, "stopall", [100], force_stop=True, timeout=60).status_code == 200
    assert writes() == [("POST", "/nodes/enzo/stopall", {"vms": "100", "force-stop": "1", "timeout": "60"})]


def test_stopall_needs_confirm_and_exact_node_name(api):
    c, cid = api
    ST["guests"] = [guest(100)]
    assert bulk(c, cid, "stopall", [100], confirm=False).status_code == 400
    for typed in (None, "", "enzo2", "ENZO", "enzo "):
        assert bulk(c, cid, "stopall", [100], type_name=typed).status_code == 400
    assert not writes()


def test_protected_machine_is_refused_even_when_confirmed(api, protected_105):
    c, cid = api
    ST["guests"] = [guest(100), guest(105), guest(116, gtype="lxc")]
    for vmids in ([105], [100, 105], [116]):
        for action, extra in (("stopall", {}), ("migrateall", {"target": "enzo2", "accept_running": True})):
            r = bulk(c, cid, action, vmids, **extra)
            assert r.status_code == 422 and "protégée" in r.json()["detail"], (action, vmids)
    assert not writes()
    ST["guests"] = [guest(105, status="stopped")]                       # démarrer une machine protégée reste permis
    assert bulk(c, cid, "startall", [105]).status_code == 200


# --- migrateall -----------------------------------------------------------------------------------------------------------------------------------------

def test_migrateall_sends_target_workers_and_local_disks_flag(api):
    c, cid = api
    ST["guests"] = [guest(100, status="stopped"), guest(101, status="stopped")]
    r = bulk(c, cid, "migrateall", [100, 101], target="enzo2", max_workers=2, with_local_disks=True)
    assert r.status_code == 200 and r.json()["vmids"] == [100, 101]
    assert writes() == [("POST", "/nodes/enzo/migrateall", {"vms": "100,101", "target": "enzo2", "maxworkers": "2", "with-local-disks": "1"})]


def test_migrateall_target_must_be_another_online_known_node(api):
    c, cid = api
    ST["guests"] = [guest(100, status="stopped")]
    ST["cluster"] = cluster([("enzo", True), ("enzo2", False), ("enzo3", True)])
    for target in (None, "enzo", "enzo2", "inconnu"):
        r = bulk(c, cid, "migrateall", [100], **({"target": target} if target else {}))
        assert r.status_code == 422, target
    assert not writes()
    assert bulk(c, cid, "migrateall", [100], target="enzo3").status_code == 200       # un nœud en ligne, différent de la source
    assert writes()[0][2]["target"] == "enzo3"


def test_migrateall_running_machines_need_explicit_acceptance(api):
    c, cid = api
    ST["guests"] = [guest(100), guest(101, status="stopped")]
    r = bulk(c, cid, "migrateall", [100, 101], target="enzo2")
    assert r.status_code == 409 and "accept_running" in r.json()["detail"] and not writes()
    assert bulk(c, cid, "migrateall", [100, 101], target="enzo2", accept_running=True).status_code == 200


def test_migrateall_needs_node_name(api):
    c, cid = api
    ST["guests"] = [guest(100, status="stopped")]
    assert bulk(c, cid, "migrateall", [100], target="enzo2", type_name="enzo2").status_code == 400
    assert not writes()


# --- liste de machines explicite -------------------------------------------------------------------------------------------------------------------------

def test_unknown_other_node_and_template_machines_are_refused_before_any_write(api):
    c, cid = api
    ST["guests"] = [guest(100, status="stopped"), guest(200, node="enzo2", status="stopped"), guest(900, status="stopped", template=1)]
    for vmids in ([999], [100, 200], [900]):
        r = bulk(c, cid, "startall", vmids)
        assert r.status_code == 422 and "absente" in r.json()["detail"], vmids
    assert not writes()


def test_vmid_list_is_validated_and_never_empty(api):
    c, cid = api
    ST["guests"] = [guest(100, status="stopped")]
    assert bulk(c, cid, "startall", []).status_code == 422
    ST["guests"] = [guest(v, status="stopped") for v in range(100, 151)]                       # 51 machines toutes valides : seule la limite refuse
    assert bulk(c, cid, "startall", list(range(100, 151))).status_code == 422 and not writes()
    assert bulk(c, cid, "startall", list(range(100, 150))).status_code == 200                   # 50 : accepté
    CALLS.clear()
    ST["guests"] = [guest(100, status="stopped")]
    assert bulk(c, cid, "startall", ["a"]).status_code == 422
    r = c.post(f"/api/connections/{cid}/nodes/enzo/bulk", json={"action": "startall", "confirm": True})          # pas de « toutes les machines »
    assert r.status_code == 422 and not writes()
    assert bulk(c, cid, "startall", [100, 100]).json()["vmids"] == [100]                                         # doublons écartés


def test_unknown_action_and_extra_fields_are_not_forwarded(api):
    c, cid = api
    ST["guests"] = [guest(100, status="stopped")]
    assert bulk(c, cid, "reboot", [100]).status_code == 422
    r = bulk(c, cid, "startall", [100], force=0, onboot=0, vms="999")                                          # champs inconnus ignorés
    assert r.status_code == 200 and writes() == [("POST", "/nodes/enzo/startall", {"vms": "100", "force": "1"})]


def test_offline_or_unknown_node(api):
    c, cid = api
    ST["guests"] = [guest(100, status="stopped")]
    ST["cluster"] = cluster([("enzo", False), ("enzo2", True)])
    assert bulk(c, cid, "startall", [100]).status_code == 409
    assert bulk(c, cid, "startall", [100], node="inconnu").status_code == 404
    assert not writes()


# --- aperçu (dry_run) -----------------------------------------------------------------------------------------------------------------------------------

def test_dry_run_writes_nothing_and_describes_the_plan(api, protected_105):
    c, cid = api
    ST["guests"] = [guest(100), guest(101, status="stopped"), guest(105)]
    r = bulk(c, cid, "migrateall", [100, 101], target="enzo2", confirm=False, type_name=None, dry_run=True)
    j = r.json()
    assert r.status_code == 200 and j["dry_run"] is True and [g["vmid"] for g in j["apply"]] == [100, 101]
    assert j["blocked"] is None and j["needs_accept_running"] is True and j["running"] == [100]
    r = bulk(c, cid, "stopall", [105], dry_run=True).json()
    assert r["protected"] == [105] and "protégée" in r["blocked"]
    r = bulk(c, cid, "startall", [100], dry_run=True).json()
    assert r["skipped"][0]["reason"] == "déjà en marche" and "Rien à faire" in r["blocked"]
    assert not writes()


# --- Proxmox refuse, audit, secrets ---------------------------------------------------------------------------------------------------------------------

def test_proxmox_refusal_is_audited_and_leaks_no_secret(api):
    c, cid = api
    ST["guests"] = [guest(100, status="stopped")]
    ST["write_fail"] = True
    r = bulk(c, cid, "startall", [100])
    assert r.status_code >= 400 and SECRET not in r.text
    log = c.get("/api/audit").json()
    assert SECRET not in c.get("/api/audit").text
    assert ("node-startall", "error") in {(a["action"], a["status"]) for a in log}


def test_success_and_refusal_are_audited(api):
    c, cid = api
    ST["guests"] = [guest(100, status="stopped")]
    assert bulk(c, cid, "startall", [100], confirm=False).status_code == 400
    assert bulk(c, cid, "startall", [100]).status_code == 200
    log = c.get("/api/audit").json()
    seen = {(a["action"], a["status"]) for a in log}
    assert ("node-startall", "started") in seen
    assert c.get("/api/audit").text.count(SECRET) == 0


def test_requires_login(client):
    assert client.post("/api/connections/1/nodes/enzo/bulk", json={"action": "startall", "vmids": [100]}).status_code == 401
    assert client.post("/api/connections/1/nodes/enzo/wakeonlan", json={}).status_code == 401


# --- Wake-on-LAN ----------------------------------------------------------------------------------------------------------------------------------------

def wake(c, cid, node="enzo2", **b):
    return c.post(f"/api/connections/{cid}/nodes/{node}/wakeonlan", json={"confirm": True, "type_name": node, **b})


def test_wake_offline_node_sends_the_packet_request(api):
    c, cid = api
    ST["cluster"] = cluster([("enzo", True), ("enzo2", False)])
    r = wake(c, cid)
    assert r.status_code == 202 and r.json() == {"node": "enzo2", "action": "wakeonlan"}
    assert writes() == [("POST", "/nodes/enzo2/wakeonlan", {})]
    assert ("node-wakeonlan", "started") in {(a["action"], a["status"]) for a in c.get("/api/audit").json()}


def test_wake_guards(api):
    c, cid = api
    ST["cluster"] = cluster([("enzo", True), ("enzo2", False)])
    assert wake(c, cid, node="enzo").status_code == 409                       # déjà en ligne
    assert wake(c, cid, node="inconnu").status_code == 404
    assert wake(c, cid, confirm=False).status_code == 400
    for typed in (None, "", "enzo", "ENZO2", "enzo2 "):
        assert wake(c, cid, type_name=typed).status_code == 400
    assert not writes()
    ST["write_fail"] = True
    r = wake(c, cid)
    assert r.status_code >= 400 and SECRET not in r.text and SECRET not in c.get("/api/audit").text
