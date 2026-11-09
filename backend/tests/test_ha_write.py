"""HA en écriture (M8-2) : faux Proxmox STRICT (méthode, paramètres et types exacts, digest vérifié, 400 sinon)."""
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
PHRASE = "COUPURE POSSIBLE"
CALLS: list[tuple[str, str, dict]] = []
ST: dict = {}
RES_KEYS = {"sid", "state", "max_restart", "max_relocate", "failback", "comment"}
RES_PUT = RES_KEYS - {"sid"} | {"delete", "digest"}
RES_DEL = {"state", "max_restart", "max_relocate", "failback", "comment"}
RULE_NODE = {"rule", "type", "resources", "nodes", "strict", "affinity", "disable", "comment"}
RULE_RES = {"rule", "type", "resources", "affinity", "disable", "comment"}
BOOLS = {"failback", "strict", "disable"}
INTS = {"max_restart", "max_relocate"}


def fresh(nodes=("enzo", "enzo2")):
    ST.clear()
    ST.update(nodes=list(nodes), noapply=False, fail=False, resources={}, rules={}, digest="d" * 40, move_reply=None)
    ST["guests"] = [{"vmid": 100, "type": "qemu", "node": "enzo", "name": "web", "status": "running", "template": 0},
                    {"vmid": 101, "type": "lxc", "node": "enzo2", "name": "ct", "status": "running", "template": 0},
                    {"vmid": 102, "type": "qemu", "node": "enzo", "name": "tpl", "status": "stopped", "template": 1},
                    {"vmid": 103, "type": "qemu", "node": "enzo", "name": "db", "status": "running", "template": 0},
                    {"vmid": 116, "type": "lxc", "node": "enzo", "name": "kaji-ct", "status": "running", "template": 0}]


def bad(msg):
    return httpx.Response(400, json={"data": None, "message": msg})


def check_types(body):
    for k, v in body.items():
        if k in BOOLS and v not in ("0", "1"):
            return f"{k} doit être 0/1"
        if k in INTS and not v.isdigit():
            return f"{k} doit être un entier"
    return None


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    m = request.method
    body = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    query = dict(request.url.params)
    if m == "GET":
        if p == "/cluster/status":
            return httpx.Response(200, json={"data": [{"type": "cluster", "name": "lab", "quorate": 1}] + [{"type": "node", "name": n, "online": 1, "ip": "10.0.0.1"} for n in ST["nodes"]]})
        if p == "/cluster/resources":
            assert query == {"type": "vm"}
            return httpx.Response(200, json={"data": [{**g, "id": f"{g['type']}/{g['vmid']}"} for g in ST["guests"]]})
        if p == "/cluster/ha/resources":
            return httpx.Response(200, json={"data": [{**r, "digest": ST["digest"]} for r in ST["resources"].values()]})
        if p == "/cluster/ha/rules":
            return httpx.Response(200, json={"data": [{**r, "digest": ST["digest"]} for r in ST["rules"].values()]})
        return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})
    if ST["fail"]:
        return httpx.Response(403, json={"data": None, "message": SECRET})
    CALLS.append((m, p, {**body, **({"__query": query} if query else {})}))
    if p == "/cluster/ha/resources" and m == "POST":
        if "sid" not in body or set(body) - RES_KEYS or check_types(body):
            return bad(f"paramètres refusés {sorted(set(body) - RES_KEYS)} {check_types(body)}")
        if body.get("state", "started") not in ("started", "stopped", "enabled", "disabled", "ignored"):
            return bad("state invalide")
        if body["sid"] in ST["resources"]:
            return bad("déjà existante")
        if not ST["noapply"]:
            r = {"sid": body["sid"], "type": body["sid"][:2], "state": body.get("state", "started")}
            for k in INTS | BOOLS | {"comment"}:
                if k in body:
                    r[k] = int(body[k]) if k in INTS | BOOLS else body[k]
            ST["resources"][body["sid"]] = r
        return httpx.Response(200, json={"data": None})
    if p.startswith("/cluster/ha/resources/"):
        rest = p.removeprefix("/cluster/ha/resources/")
        sid, _, act = rest.partition("/")
        r = ST["resources"].get(sid)
        if r is None:
            return httpx.Response(500, json={"data": None, "message": "no such resource"})
        if m == "PUT" and not act:
            if set(body) - RES_PUT or check_types(body):
                return bad(f"paramètres refusés {sorted(set(body) - RES_PUT)} {check_types(body)}")
            if body.get("digest") != ST["digest"]:
                return bad("digest différent")
            dl = [x for x in body.get("delete", "").split(",") if x]
            if set(dl) - RES_DEL:
                return bad("delete invalide")
            if not ST["noapply"]:
                for k, v in body.items():
                    if k not in ("delete", "digest"):
                        r[k] = int(v) if k in INTS | BOOLS else v
                for k in dl:
                    r.pop(k, None)
            return httpx.Response(200, json={"data": None})
        if m == "DELETE" and not act:
            if set(body) | set(query) - {"purge"} or query.get("purge") != "0":
                return bad("purge=0 attendu")
            if not ST["noapply"]:
                del ST["resources"][sid]
            return httpx.Response(200, json={"data": None})
        if m == "POST" and act in ("migrate", "relocate"):
            if set(body) != {"node"} or body["node"] not in ST["nodes"]:
                return bad("node invalide")
            return httpx.Response(200, json={"data": ST["move_reply"] or {"sid": sid, "requested-node": body["node"]}})
    if p == "/cluster/ha/rules" and m == "POST":
        allowed = RULE_NODE if body.get("type") == "node-affinity" else RULE_RES if body.get("type") == "resource-affinity" else set()
        if set(body) - allowed or check_types(body) or not {"rule", "type", "resources"} <= set(body):
            return bad(f"paramètres refusés {sorted(set(body) - allowed)}")
        if body["type"] == "node-affinity" and "nodes" not in body or body["type"] == "resource-affinity" and "affinity" not in body:
            return bad("paramètre obligatoire manquant")
        if body["rule"] in ST["rules"]:
            return bad("règle existante")
        if not ST["noapply"]:
            ST["rules"][body["rule"]] = {**{k: (int(v) if k in BOOLS else v) for k, v in body.items()}}
        return httpx.Response(200, json={"data": None})
    if p.startswith("/cluster/ha/rules/"):
        name = p.removeprefix("/cluster/ha/rules/")
        r = ST["rules"].get(name)
        if r is None:
            return httpx.Response(500, json={"data": None, "message": "no such rule"})
        if m == "PUT":
            allowed = (RULE_NODE if r["type"] == "node-affinity" else RULE_RES) - {"rule"} | {"delete", "digest"}
            if set(body) - allowed or check_types(body) or body.get("type") != r["type"]:
                return bad(f"paramètres refusés {sorted(set(body) - allowed)}")
            if body.get("digest") != ST["digest"]:
                return bad("digest différent")
            if not ST["noapply"]:
                for k, v in body.items():
                    if k not in ("delete", "digest"):
                        r[k] = int(v) if k in BOOLS else v
                for k in [x for x in body.get("delete", "").split(",") if x]:
                    r.pop(k, None)
            return httpx.Response(200, json={"data": None})
        if m == "DELETE":
            if body or query:
                return bad("aucun paramètre attendu")
            if not ST["noapply"]:
                del ST["rules"][name]
            return httpx.Response(200, json={"data": None})
    return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})


@pytest.fixture
def api(client, monkeypatch):
    CALLS.clear()
    fresh()
    monkeypatch.setattr("app.routers.ha_write.get_settings", lambda: SimpleNamespace(protected_vmids={116}))
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def url(cid, path):
    return f"/api/connections/{cid}/ha{path}"


def ok(extra=None):
    return {"confirm": True, "acknowledge_live": True, "acknowledge_cut_access": True, "type_name": PHRASE, **(extra or {})}


def add_res(sid="vm:100", **kw):
    ST["resources"][sid] = {"sid": sid, "type": sid[:2], "state": "started", "max_restart": 1, "max_relocate": 1, **kw}


def add_rule(name="r1", **kw):
    ST["rules"][name] = {"rule": name, "type": "node-affinity", "resources": "vm:100", "nodes": "enzo:2,enzo2", "strict": 0, **kw}


def audit_pairs(c):
    return [(a["action"], a["status"]) for a in c.get("/api/audit").json()]


# ---------------------------------------------------------------- ressources : création
def test_create_resource_needs_cut_unlock_on_two_nodes(api):
    c, cid = api
    r = c.post(url(cid, "/resources"), json={"sid": "vm:100", "confirm": True})
    assert r.status_code == 409 and "Coupure possible" in r.json()["detail"] and PHRASE in r.json()["detail"] and not CALLS
    for extra in ({"acknowledge_cut_access": True}, {"acknowledge_live": True, "type_name": PHRASE}, {"acknowledge_cut_access": True, "type_name": "coupure possible"}):
        assert c.post(url(cid, "/resources"), json={"sid": "vm:100", "confirm": True, **extra}).status_code == 409
    assert not CALLS and not ST["resources"]
    r = c.post(url(cid, "/resources"), json={"sid": "vm:100", "state": "started", "max_restart": 2, "max_relocate": 0, "failback": False, "comment": "web", **ok()})
    assert r.status_code == 200 and r.json()["created"] == "vm:100"
    assert CALLS == [("POST", "/cluster/ha/resources", {"sid": "vm:100", "state": "started", "max_restart": "2", "max_relocate": "0", "failback": "0", "comment": "web"})]
    assert ST["resources"]["vm:100"]["failback"] == 0


def test_create_with_three_nodes_needs_only_live_ack(api):
    c, cid = api
    fresh(("enzo", "enzo2", "enzo3"))
    r = c.post(url(cid, "/resources"), json={"sid": "ct:101", "confirm": True})
    assert r.status_code == 409 and "Effet immédiat" in r.json()["detail"] and not CALLS
    assert c.post(url(cid, "/resources"), json={"sid": "ct:101", "confirm": True, "acknowledge_live": True}).status_code == 200
    assert CALLS[-1][2] == {"sid": "ct:101"}


def test_create_inactive_resource_is_inert_even_on_two_nodes(api):
    c, cid = api
    for state in ("ignored", "disabled"):
        ST["resources"].clear(); CALLS.clear()
        r = c.post(url(cid, "/resources"), json={"sid": "vm:103", "state": state, "confirm": True})
        assert r.status_code == 200 and r.json()["locks"]["inert"] is True and CALLS[-1][2]["state"] == state


def test_dry_run_writes_nothing_and_shows_locks(api):
    c, cid = api
    r = c.post(url(cid, "/resources"), json={"sid": "vm:100", "dry_run": True})
    assert r.status_code == 200 and r.json()["dry_run"] is True and r.json()["phrase"] == PHRASE and r.json()["locks"]["cut"] and r.json()["params"] == {"sid": "vm:100"}
    assert not CALLS and not ST["resources"]


def test_confirm_is_required_and_strict(api):
    c, cid = api
    assert c.post(url(cid, "/resources"), json={"sid": "vm:100", **ok({"confirm": False})}).status_code == 400
    assert c.post(url(cid, "/resources"), json={"sid": "vm:100", **ok({"confirm": "true"})}).status_code == 422
    assert not CALLS


@pytest.mark.parametrize("b", [{"sid": "vm:1"}, {"sid": "qemu:100"}, {"sid": "vm:100,vm:101"}, {"sid": "vm:100", "state": "bogus"}, {"sid": "vm:100", "max_restart": 11},
                               {"sid": "vm:100", "max_restart": -1}, {"sid": "vm:100", "max_restart": "1"}, {"sid": "vm:100", "failback": "1"}, {"sid": "vm:100", "comment": "a\nb"},
                               {"sid": "vm:100", "comment": "x" * 501}, {"sid": "../x"}, {}])
def test_invalid_create_is_refused_without_any_call(api, b):
    c, cid = api
    assert c.post(url(cid, "/resources"), json={**ok(), **b}).status_code == 422 and not CALLS


def test_unknown_fields_are_never_forwarded(api):
    c, cid = api
    r = c.post(url(cid, "/resources"), json={"sid": "vm:100", "group": "g", "type": "ct", "auto-rebalance": 1, "hookscript": "x", **ok()})
    assert r.status_code == 200 and CALLS[-1][2] == {"sid": "vm:100"}


def test_create_refusals_unknown_template_duplicate(api):
    c, cid = api
    assert c.post(url(cid, "/resources"), json={"sid": "vm:999", **ok()}).status_code == 404
    assert c.post(url(cid, "/resources"), json={"sid": "ct:100", **ok()}).status_code == 404            # 100 est une VM, pas un conteneur
    assert c.post(url(cid, "/resources"), json={"sid": "vm:102", **ok()}).status_code == 422            # modèle
    add_res("vm:100")
    assert c.post(url(cid, "/resources"), json={"sid": "vm:100", **ok()}).status_code == 409
    assert not CALLS


# ---------------------------------------------------------------- machine de Kaji : interdit même confirmé
def test_protected_machine_is_refused_everywhere_even_fully_unlocked(api):
    c, cid = api
    r = c.post(url(cid, "/resources"), json={"sid": "ct:116", **ok()})
    assert r.status_code == 403 and "protégée" in r.json()["detail"]
    assert c.post(url(cid, "/resources"), json={"sid": "ct:116", "dry_run": True}).status_code == 403
    add_res("ct:116")
    assert c.put(url(cid, "/resources/ct:116"), json={"comment": "x", **ok()}).status_code == 403
    assert c.post(url(cid, "/resources/ct:116/migrate"), json={"node": "enzo2", **ok()}).status_code == 403
    assert c.post(url(cid, "/resources/ct:116/relocate"), json={"node": "enzo2", **ok()}).status_code == 403
    add_res("vm:100")
    assert c.post(url(cid, "/rules"), json={"rule": "kaji", "type": "node-affinity", "resources": ["ct:116"], "nodes": [{"node": "enzo"}], **ok()}).status_code == 403
    assert not CALLS


def test_protected_machine_cannot_be_dragged_by_a_positive_affinity(api):
    c, cid = api
    add_res("vm:100"); add_res("ct:116")
    ST["rules"]["together"] = {"rule": "together", "type": "resource-affinity", "resources": "vm:100,ct:116", "affinity": "positive"}
    r = c.post(url(cid, "/resources/vm:100/migrate"), json={"node": "enzo2", **ok()})
    assert r.status_code == 403 and "ct:116" in r.json()["detail"] and not CALLS
    ST["rules"]["together"]["disable"] = 1                                                               # règle désactivée : plus d'entraînement
    assert c.post(url(cid, "/resources/vm:100/migrate"), json={"node": "enzo2", **ok()}).status_code == 200


def test_removing_a_protected_machine_from_ha_stays_possible(api):
    c, cid = api
    add_res("ct:116")
    assert c.delete(url(cid, "/resources/ct:116"), params={"confirm": True, "acknowledge_live": True}).status_code == 200
    assert "ct:116" not in ST["resources"]


# ---------------------------------------------------------------- ressources : modification
def test_update_resource_sends_digest_clear_and_verifies(api):
    c, cid = api
    add_res("vm:100", comment="old", max_relocate=3)
    r = c.put(url(cid, "/resources/vm:100"), json={"state": "stopped", "max_restart": 2, "clear": ["comment", "max_relocate"], **ok()})
    assert r.status_code == 200 and r.json()["removed"] == ["comment", "max_relocate"]
    assert CALLS[-1] == ("PUT", "/cluster/ha/resources/vm:100", {"state": "stopped", "max_restart": "2", "delete": "comment,max_relocate", "digest": "d" * 40})
    assert ST["resources"]["vm:100"]["state"] == "stopped" and "comment" not in ST["resources"]["vm:100"]


def test_update_locks_and_refusals(api):
    c, cid = api
    assert c.put(url(cid, "/resources/vm:100"), json={"comment": "x", **ok()}).status_code == 404
    add_res("vm:100")
    assert c.put(url(cid, "/resources/vm:100"), json={"comment": "x", "confirm": True}).status_code == 409                     # 2 nœuds : phrase
    assert c.put(url(cid, "/resources/vm:100"), json={"comment": "x", "confirm": True, "acknowledge_live": True}).status_code == 409
    for b in ({}, {"clear": []}, {"comment": "x", "clear": ["comment"]}, {"clear": ["sid"]}, {"clear": ["state"]}, {"sid": "vm:101"}):
        assert c.put(url(cid, "/resources/vm:100"), json={**ok(), **b}).status_code == 422 or b == {"sid": "vm:101"}
    assert not CALLS


def test_update_of_inactive_resource_without_activation_is_inert(api):
    c, cid = api
    add_res("vm:100", state="disabled")
    r = c.put(url(cid, "/resources/vm:100"), json={"comment": "x", "confirm": True})
    assert r.status_code == 409 and "Effet immédiat" in r.json()["detail"]                                # existe déjà : effet direct, mais pas de coupure
    assert c.put(url(cid, "/resources/vm:100"), json={"comment": "x", "confirm": True, "acknowledge_live": True}).status_code == 200


def test_update_with_changed_digest_is_refused_by_proxmox(api):
    c, cid = api
    add_res("vm:100")
    ST["digest"] = "e" * 40                                                                                # relu juste avant : le digest suit
    assert c.put(url(cid, "/resources/vm:100"), json={"comment": "x", **ok()}).status_code == 200


# ---------------------------------------------------------------- ressources : suppression
def test_delete_resource_purge_zero_and_rules_guard(api):
    c, cid = api
    add_res("vm:100"); add_rule("r1", resources="vm:100")
    r = c.delete(url(cid, "/resources/vm:100"), params={"confirm": True, "acknowledge_live": True})
    assert r.status_code == 409 and "r1" in r.json()["detail"] and not CALLS
    ST["rules"].clear()
    assert c.delete(url(cid, "/resources/vm:100"), params={"confirm": True}).status_code == 409           # effet direct : acknowledge_live
    assert c.delete(url(cid, "/resources/vm:100"), params={"acknowledge_live": True}).status_code == 400  # confirm obligatoire
    r = c.delete(url(cid, "/resources/vm:100"), params={"confirm": True, "acknowledge_live": True})
    assert r.status_code == 200 and CALLS == [("DELETE", "/cluster/ha/resources/vm:100", {"__query": {"purge": "0"}})] and not ST["resources"]
    assert c.delete(url(cid, "/resources/vm:100"), params={"confirm": True, "acknowledge_live": True}).status_code == 404


def test_delete_dry_run(api):
    c, cid = api
    add_res("vm:100")
    r = c.delete(url(cid, "/resources/vm:100"), params={"dry_run": True})
    assert r.status_code == 200 and r.json()["dry_run"] is True and not CALLS and "vm:100" in ST["resources"]


# ---------------------------------------------------------------- migrer / relocaliser
@pytest.mark.parametrize("kind", ["migrate", "relocate"])
def test_move_checks_and_sends_exact_params(api, kind):
    c, cid = api
    add_res("vm:100")
    assert c.post(url(cid, f"/resources/vm:100/{kind}"), json={"node": "enzo2", "confirm": True, "acknowledge_live": True}).status_code == 409     # 2 nœuds
    assert c.post(url(cid, f"/resources/vm:100/{kind}"), json={"node": "enzo", **ok()}).status_code == 409                                         # déjà là
    assert c.post(url(cid, f"/resources/vm:100/{kind}"), json={"node": "nope", **ok()}).status_code == 422
    assert c.post(url(cid, f"/resources/vm:100/{kind}"), json={"node": "enzo2; rm", **ok()}).status_code == 422
    assert c.post(url(cid, f"/resources/vm:103/{kind}"), json={"node": "enzo2", **ok()}).status_code == 404                                        # pas en HA
    assert not CALLS
    r = c.post(url(cid, f"/resources/vm:100/{kind}"), json={"node": "enzo2", **ok()})
    assert r.status_code == 200 and r.json()["from"] == "enzo" and r.json()["requested"] == "enzo2"
    assert CALLS == [("POST", f"/cluster/ha/resources/vm:100/{kind}", {"node": "enzo2"})]


def test_move_reports_blocking_and_comigrated_shaped(api):
    c, cid = api
    add_res("vm:100"); add_res("vm:103")
    ST["move_reply"] = {"sid": "vm:100", "requested-node": "enzo2", "comigrated-resources": ["vm:103", "../x", 5], "evil": SECRET,
                        "blocking-resources": [{"sid": "vm:103", "cause": "node-affinity"}, {"sid": "bad", "cause": "x"}, "junk", {"sid": "vm:101", "cause": "zzz"}]}
    r = c.post(url(cid, "/resources/vm:100/migrate"), json={"node": "enzo2", **ok()})
    assert r.status_code == 200 and SECRET not in r.text
    assert r.json()["comigrated"] == ["vm:103"] and r.json()["blocking"] == [{"sid": "vm:103", "cause": "node-affinity"}, {"sid": "vm:101", "cause": None}]


def test_move_dry_run_announces_comigrated_resources(api):
    c, cid = api
    add_res("vm:100"); add_res("vm:103")
    ST["rules"]["together"] = {"rule": "together", "type": "resource-affinity", "resources": "vm:100,vm:103", "affinity": "positive"}
    r = c.post(url(cid, "/resources/vm:100/migrate"), json={"node": "enzo2", "dry_run": True})
    assert r.status_code == 200 and r.json()["comigrated"] == ["vm:103"] and r.json()["from"] == "enzo" and not CALLS


def test_move_to_offline_node_is_refused(api):
    c, cid = api
    add_res("vm:100")
    ST["nodes"].append("enzo3")
    orig = _handler

    def handler(request):
        r = orig(request)
        if request.url.path.endswith("/cluster/status"):
            data = r.json()["data"]
            for d in data:
                if d.get("name") == "enzo3":
                    d["online"] = 0
            return httpx.Response(200, json={"data": data})
        return r
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(handler)))
    assert c.post(url(cid, "/resources/vm:100/migrate"), json={"node": "enzo3", "confirm": True, "acknowledge_live": True}).status_code == 422
    assert not CALLS


# ---------------------------------------------------------------- règles
NA = {"rule": "pref", "type": "node-affinity", "resources": ["vm:100", "ct:101"], "nodes": [{"node": "enzo", "priority": 2}, {"node": "enzo2"}], "strict": True, "comment": "c"}


def test_create_node_affinity_rule_exact_params(api):
    c, cid = api
    add_res("vm:100"); add_res("ct:101")
    r = c.post(url(cid, "/rules"), json={**NA, **ok()})
    assert r.status_code == 200
    assert CALLS == [("POST", "/cluster/ha/rules", {"rule": "pref", "type": "node-affinity", "resources": "vm:100,ct:101", "nodes": "enzo:2,enzo2", "strict": "1", "comment": "c"})]


def test_create_resource_affinity_rule(api):
    c, cid = api
    add_res("vm:100"); add_res("ct:101")
    r = c.post(url(cid, "/rules"), json={"rule": "apart", "type": "resource-affinity", "resources": ["vm:100", "ct:101"], "affinity": "negative", **ok()})
    assert r.status_code == 200 and CALLS[-1][2] == {"rule": "apart", "type": "resource-affinity", "resources": "vm:100,ct:101", "affinity": "negative"}


def test_disabled_rule_is_inert_and_rule_locks(api):
    c, cid = api
    add_res("vm:100")
    base = {"rule": "r", "type": "node-affinity", "resources": ["vm:100"], "nodes": [{"node": "enzo"}], "confirm": True}
    assert c.post(url(cid, "/rules"), json=base).status_code == 409
    r = c.post(url(cid, "/rules"), json={**base, "disable": True})
    assert r.status_code == 200 and r.json()["locks"]["inert"] is True and CALLS[-1][2]["disable"] == "1"


@pytest.mark.parametrize("b", [
    {"resources": []}, {"resources": ["vm:100", "vm:100"]}, {"resources": ["bad"]}, {"nodes": []}, {"nodes": [{"node": "a b"}]}, {"nodes": [{"node": "enzo"}, {"node": "enzo"}]},
    {"nodes": [{"node": "enzo", "priority": -1}]}, {"nodes": [{"node": "enzo", "priority": 1001}]}, {"rule": "1bad"}, {"rule": "a b"}, {"rule": ""}, {"strict": "1"},
    {"type": "group"}, {"affinity": "maybe"}, {"comment": "a\x00b"},
    {"type": "resource-affinity", "affinity": "positive", "nodes": [{"node": "enzo"}], "resources": ["vm:100", "ct:101"]},
    {"type": "resource-affinity", "affinity": "positive", "resources": ["vm:100", "ct:101"], "strict": True},
    {"type": "resource-affinity", "resources": ["vm:100", "ct:101"]}, {"type": "resource-affinity", "affinity": "positive", "resources": ["vm:100"], "nodes": None},
])
def test_invalid_rule_is_refused_without_any_call(api, b):
    c, cid = api
    add_res("vm:100"); add_res("ct:101")
    base = {"rule": "r", "type": "node-affinity", "resources": ["vm:100"], "nodes": [{"node": "enzo"}]}
    assert c.post(url(cid, "/rules"), json={**base, **ok(), **b}).status_code == 422 and not CALLS


def test_rule_requires_known_resources_nodes_and_unique_name(api):
    c, cid = api
    add_res("vm:100")
    base = {"rule": "r", "type": "node-affinity", "resources": ["vm:100"], "nodes": [{"node": "enzo"}], **ok()}
    assert c.post(url(cid, "/rules"), json={**base, "resources": ["vm:100", "vm:103"]}).status_code == 422                   # vm:103 pas en HA
    assert c.post(url(cid, "/rules"), json={**base, "nodes": [{"node": "ghost"}]}).status_code == 422
    assert c.post(url(cid, "/rules"), json={k: v for k, v in base.items() if k != "nodes"}).status_code == 422
    add_rule("r")
    assert c.post(url(cid, "/rules"), json=base).status_code == 409
    assert not CALLS


def test_update_rule(api):
    c, cid = api
    add_res("vm:100"); add_res("ct:101"); add_rule("r1", comment="old")
    r = c.put(url(cid, "/rules/r1"), json={"type": "node-affinity", "resources": ["vm:100", "ct:101"], "nodes": [{"node": "enzo2", "priority": 5}], "strict": True,
                                           "clear": ["comment"], **ok()})
    assert r.status_code == 200 and sorted(r.json()["changed"]) == ["nodes", "resources", "strict"]
    assert CALLS[-1] == ("PUT", "/cluster/ha/rules/r1", {"type": "node-affinity", "resources": "vm:100,ct:101", "nodes": "enzo2:5", "strict": "1", "delete": "comment", "digest": "d" * 40})


def test_update_rule_refusals(api):
    c, cid = api
    add_res("vm:100"); add_rule("r1")
    assert c.put(url(cid, "/rules/nope"), json={"type": "node-affinity", "comment": "x", **ok()}).status_code == 404
    assert c.put(url(cid, "/rules/r1"), json={"type": "resource-affinity", "comment": "x", **ok()}).status_code == 422          # type figé
    assert c.put(url(cid, "/rules/r1"), json={"type": "node-affinity", **ok()}).status_code == 422                                # rien à changer
    assert c.put(url(cid, "/rules/r1"), json={"type": "node-affinity", "comment": "x", "clear": ["comment"], **ok()}).status_code == 422
    assert c.put(url(cid, "/rules/r1"), json={"type": "node-affinity", "comment": "x", "clear": ["nodes"], **ok()}).status_code == 422
    assert c.put(url(cid, "/rules/r1"), json={"type": "node-affinity", "comment": "x", "confirm": True}).status_code == 409
    assert not CALLS


def test_delete_rule(api):
    c, cid = api
    add_rule("r1")
    assert c.delete(url(cid, "/rules/r1"), params={"confirm": True}).status_code == 409
    assert c.delete(url(cid, "/rules/r1"), params={"dry_run": True}).status_code == 200 and "r1" in ST["rules"] and not CALLS
    assert c.delete(url(cid, "/rules/r1"), params={"confirm": True, "acknowledge_live": True}).status_code == 200
    assert CALLS == [("DELETE", "/cluster/ha/rules/r1", {})] and not ST["rules"]
    assert c.delete(url(cid, "/rules/r1"), params={"confirm": True, "acknowledge_live": True}).status_code == 404


# ---------------------------------------------------------------- relecture, audit, secrets
def _setup_unapplied():
    add_res("vm:103"); add_rule("r1", resources="vm:100"); add_res("vm:100")


@pytest.mark.parametrize("call", [
    lambda c, cid: c.post(url(cid, "/resources"), json={"sid": "ct:101", **ok()}),
    lambda c, cid: c.put(url(cid, "/resources/vm:103"), json={"comment": "x", **ok()}),
    lambda c, cid: c.delete(url(cid, "/resources/vm:103"), params={"confirm": True, "acknowledge_live": True}),
    lambda c, cid: c.post(url(cid, "/rules"), json={**NA, "resources": ["vm:103"], **ok()}),
    lambda c, cid: c.put(url(cid, "/rules/r1"), json={"type": "node-affinity", "comment": "x", **ok()}),
    lambda c, cid: c.delete(url(cid, "/rules/r1"), params={"confirm": True, "acknowledge_live": True}),
], ids=["res-create", "res-update", "res-delete", "rule-create", "rule-update", "rule-delete"])
def test_unapplied_change_is_a_502_not_a_success(api, call):
    c, cid = api
    _setup_unapplied()
    ST["noapply"] = True
    r = call(c, cid)
    assert r.status_code == 502 and "n'a pas" in r.json()["detail"]
    assert audit_pairs(c)[-1][1] == "error"


def test_every_write_and_refusal_is_audited_without_secret(api):
    c, cid = api
    c.post(url(cid, "/resources"), json={"sid": "vm:100", "confirm": True})                              # refus (verrou)
    c.post(url(cid, "/resources"), json={"sid": "vm:100", **ok({"comment": "visible-no"})})              # succès
    c.post(url(cid, "/resources"), json={"sid": "ct:116", **ok()})                                       # refus (protégée)
    pairs = audit_pairs(c)
    assert pairs.count(("ha-resource-create", "error")) == 2 and pairs.count(("ha-resource-create", "started")) == 1
    assert SECRET not in c.get("/api/audit").text
    detail = " ".join(a.get("detail") or "" for a in c.get("/api/audit").json())
    assert "visible-no" not in detail                                                                    # le commentaire n'est pas copié dans l'audit


def test_proxmox_error_never_leaks_its_message(api):
    c, cid = api
    add_res("vm:100")
    ST["fail"] = True
    r = c.put(url(cid, "/resources/vm:100"), json={"comment": "x", **ok()})
    assert r.status_code == 502 and SECRET not in r.text and SECRET not in c.get("/api/audit").text
    assert audit_pairs(c)[-1] == ("ha-resource-update", "error")


def test_routes_require_authentication(client):
    for m, p in (("post", "/resources"), ("put", "/resources/vm:100"), ("delete", "/resources/vm:100"), ("post", "/resources/vm:100/migrate"), ("post", "/rules"),
                 ("put", "/rules/r"), ("delete", "/rules/r")):
        assert getattr(client, m)(url(1, p)).status_code == 401
