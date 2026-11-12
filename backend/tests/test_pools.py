"""Pools de ressources en écriture (lot #298) : faux Proxmox STRICT avec état. Ce fichier ne prouve rien sur un vrai cluster.

Le faux suit le schéma de Proxmox 9 (apidoc) : `POST/PUT/DELETE /pools` avec `poolid` en paramètre ; `PUT` n'accepte que `poolid, comment, vms, storage, delete,
allow-move` ; supprimer un pool non vide échoue ; ajouter une machine déjà dans un autre pool échoue sans `allow-move`. Tout autre paramètre répond 400.
"""
from urllib.parse import parse_qs

import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.poolspec import POOLID, PoolUpdate, plan_calls, shape_member, shape_pool
from app.proxmox import ProxmoxClient
from app.routers.pools import POOL_PATH

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
CALLS: list[dict] = []
STATE: dict = {}
PUT_KEYS = {"poolid", "comment", "vms", "storage", "delete", "allow-move"}


def reset():
    STATE.clear()
    STATE.update(
        pools={"kaji-test": {"comment": "bac à sable", "vms": [115], "storage": []}, "autre": {"comment": None, "vms": [120], "storage": ["local"]}, "vide": {"comment": None, "vms": [], "storage": []}},
        resources=[{"vmid": v, "type": "qemu", "node": "enzo"} for v in (105, 115, 117, 120, 121)],
        storages=[{"storage": s} for s in ("local", "local-lvm")],
        acl=[{"path": "/pool/kaji-test", "type": "user", "ugid": "kaji@pve", "roleid": "PVEVMAdmin"}, {"path": "/vms", "type": "user", "ugid": "kaji@pve", "roleid": "PVEAuditor"}],
        fail=None, acl_unreadable=False,
    )


def _members(p):
    return ([{"id": f"qemu/{v}", "node": "enzo", "type": "qemu", "vmid": v, "name": f"vm{v}", "status": "stopped", "uptime": 0} for v in p["vms"]]
            + [{"id": f"storage/enzo/{s}", "node": "enzo", "type": "storage", "storage": s} for s in p["storage"]])


def _json(code, data=None):
    return httpx.Response(code, json={"data": data})


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/api2/json")
    form = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()} if request.content else {}
    query = dict(request.url.params)
    CALLS.append({"method": request.method, "path": path, "form": form, "query": query})
    if STATE["fail"] and (request.method, path) == STATE["fail"][:2]:
        return _json(STATE["fail"][2])
    pools = STATE["pools"]
    if request.method == "GET" and path == "/pools":
        return _json(400) if set(query) - {"poolid", "type"} else _json(200, [{"poolid": k, "comment": v["comment"], "members": _members(v)} for k, v in pools.items()
                                                                              if "poolid" not in query or query["poolid"] == k])
    if request.method == "GET" and path == "/cluster/resources":
        return _json(400) if set(query) != {"type"} or query["type"] != "vm" else _json(200, STATE["resources"])
    if request.method == "GET" and path == "/storage":
        return _json(400) if query else _json(200, STATE["storages"])
    if request.method == "GET" and path == "/access/acl":
        return _json(500) if STATE["acl_unreadable"] else _json(200, STATE["acl"])
    if request.method == "POST" and path == "/pools":
        if set(form) - {"poolid", "comment"} or "poolid" not in form or query or form["poolid"] in pools:
            return _json(400 if form["poolid"] not in pools else 500)
        pools[form["poolid"]] = {"comment": form.get("comment"), "vms": [], "storage": []}
        return _json(200)
    if request.method == "PUT" and path == "/pools":
        if set(form) - PUT_KEYS or "poolid" not in form or query or form["poolid"] not in pools:
            return _json(400)
        p = pools[form["poolid"]]
        vms = [int(x) for x in form["vms"].split(",")] if "vms" in form else []
        sto = form["storage"].split(",") if "storage" in form else []
        if form.get("delete") == "1":
            if any(v not in p["vms"] for v in vms) or any(s not in p["storage"] for s in sto):
                return _json(500)
            p["vms"] = [v for v in p["vms"] if v not in vms]
            p["storage"] = [s for s in p["storage"] if s not in sto]
            return _json(200)
        for v in vms:
            holder = next((k for k, q in pools.items() if v in q["vms"] and k != form["poolid"]), None)
            if holder and form.get("allow-move") != "1":
                return _json(500)
            if holder:
                pools[holder]["vms"].remove(v)
            if v not in p["vms"]:
                p["vms"].append(v)
        p["storage"] += [s for s in sto if s not in p["storage"]]
        if "comment" in form:
            p["comment"] = form["comment"]
        return _json(200)
    if request.method == "DELETE" and path == "/pools":
        if set(query) != {"poolid"} or form or query["poolid"] not in pools:
            return _json(400)
        if pools[query["poolid"]]["vms"] or pools[query["poolid"]]["storage"]:
            return _json(500)
        del pools[query["poolid"]]
        return _json(200)
    return _json(404)


@pytest.fixture
def api(client):
    CALLS.clear()
    reset()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def u(cid, suffix=""):
    return f"/api/connections/{cid}/pools{suffix}"


def writes():
    return [x for x in CALLS if x["method"] != "GET"]


def audit(c):
    return c.get("/api/audit").json()


# ------------------------------------------------------------------ purs

def test_path_and_body_patterns_are_aligned():
    assert POOL_PATH.metadata[0].pattern == "^" + POOLID.pattern + "$" if hasattr(POOL_PATH, "metadata") else True
    for good in ("a", "kaji-test", "Pool_1", "x" * 40):
        assert POOLID.fullmatch(good)
    for bad in ("", "-a", "_a", "a b", "a/b", "a..b", "x" * 41, "a\n", "é", "a;b"):
        assert not POOLID.fullmatch(bad)


def test_shape_member_whitelists_fields():
    m = shape_member({"type": "qemu", "vmid": 115, "name": "vm", "node": "enzo", "status": "stopped", "uptime": 5, "secret": SECRET, "id": "qemu/115"})
    assert m == {"type": "qemu", "vmid": 115, "name": "vm", "node": "enzo", "status": "stopped"}
    assert shape_member({"type": "openvz", "vmid": 9, "node": "n"})["type"] == "lxc"
    assert shape_member({"type": "storage", "storage": "local", "node": "enzo", "id": "x"}) == {"type": "storage", "storage": "local", "node": "enzo"}
    for bad in (None, 5, {"type": "qemu"}, {"type": "qemu", "vmid": True}, {"type": "storage", "storage": "../x"}, {"type": "autre", "vmid": 1}):
        assert shape_member(bad) is None


def test_shape_pool_rejects_bad_ids_and_sorts():
    assert shape_pool({"poolid": "../x"}) is None and shape_pool({"poolid": 5}) is None and shape_pool("x") is None
    p = shape_pool({"poolid": "a", "comment": "c", "members": [{"type": "qemu", "vmid": 120}, {"type": "qemu", "vmid": 105}, {"type": "storage", "storage": "local"}, "x"]})
    assert p["vms"] == [105, 120] and p["storages"] == ["local"] and len(p["members"]) == 3


def test_plan_calls_orders_adds_before_removals():
    b = PoolUpdate(comment="c", add_vms=[117], remove_vms=[115], add_storage=["local"], remove_storage=["local-lvm"], allow_move=True)
    assert plan_calls("p", b) == [{"poolid": "p", "comment": "c", "vms": "117", "storage": "local", "allow-move": 1},
                                  {"poolid": "p", "delete": 1, "vms": "115", "storage": "local-lvm"}]
    assert plan_calls("p", PoolUpdate(remove_vms=[1, 2] if False else [115])) == [{"poolid": "p", "delete": 1, "vms": "115"}]
    assert plan_calls("p", PoolUpdate(allow_move=True, comment="")) == [{"poolid": "p", "comment": ""}]            # allow-move sans machine à ajouter : jamais envoyé


# ------------------------------------------------------------------ lecture

def test_requires_auth(client):
    for m, s in (("get", "/overview"), ("get", "/x"), ("post", ""), ("put", "/x"), ("delete", "/x")):
        assert getattr(client, m)(f"/api/connections/1/pools{s}").status_code == 401


def test_overview_and_detail_never_write(api):
    c, cid = api
    o = c.get(u(cid, "/overview")).json()
    assert [p["poolid"] for p in o] == ["autre", "kaji-test", "vide"]
    d = c.get(u(cid, "/kaji-test")).json()
    assert d["vms"] == [115] and d["members"][0] == {"type": "qemu", "vmid": 115, "name": "vm115", "node": "enzo", "status": "stopped"}
    assert c.get(u(cid, "/inconnu")).status_code == 404 and writes() == []
    assert c.get(u(cid, "/a b")).status_code == 422 and c.get(u(cid, "/-x")).status_code == 422


def test_existing_simple_list_still_works(api):
    c, cid = api
    r = c.get(u(cid))
    assert r.status_code == 200 and [p["poolid"] for p in r.json()] == ["autre", "kaji-test", "vide"]


# ------------------------------------------------------------------ création

def test_create_exact_call_and_audit(api):
    c, cid = api
    r = c.post(u(cid), json={"poolid": "essai", "comment": "un pool", "inconnu": 1, "vms": "115"})
    assert r.status_code == 201 and r.json() == {"poolid": "essai"}
    assert [(w["path"], w["form"]) for w in writes()] == [("/pools", {"poolid": "essai", "comment": "un pool"})]
    assert STATE["pools"]["essai"]["vms"] == []
    last = audit(c)[0]
    assert (last["action"], last["status"], last["target"]) == ("pool-create", "started", "pool/essai")


def test_create_without_comment(api):
    c, cid = api
    assert c.post(u(cid), json={"poolid": "essai"}).status_code == 201 and writes()[0]["form"] == {"poolid": "essai"}


def test_create_duplicate_is_409_without_write(api):
    c, cid = api
    assert c.post(u(cid), json={"poolid": "vide"}).status_code == 409 and writes() == []
    assert (audit(c)[0]["action"], audit(c)[0]["status"]) == ("pool-create", "error")


@pytest.mark.parametrize("body", [{"poolid": "../x"}, {"poolid": "a b"}, {"poolid": ""}, {"poolid": "x" * 41}, {"poolid": "-a"}, {"poolid": "a/b"}, {"poolid": 5},
                                  {}, {"poolid": "ok", "comment": "x" * 201}, {"poolid": "ok", "comment": "a\x00b"}, {"poolid": "ok", "comment": "a\rb"}])
def test_create_invalid_input_is_422_without_call(api, body):
    c, cid = api
    r = c.post(u(cid), json=body)
    assert r.status_code == 422 and CALLS == [] and SECRET not in r.text


# ------------------------------------------------------------------ modification

def put(c, cid, poolid="vide", **body):
    return c.put(u(cid, f"/{poolid}"), json=body)


def test_update_comment_and_add_members(api):
    c, cid = api
    r = put(c, cid, comment="nouveau", add_vms=[117], add_storage=["local-lvm"])
    assert r.status_code == 200 and r.json()["pool"]["vms"] == [117] and r.json()["pool"]["storages"] == ["local-lvm"]
    assert [(w["method"], w["path"], w["form"]) for w in writes()] == [("PUT", "/pools", {"poolid": "vide", "comment": "nouveau", "vms": "117", "storage": "local-lvm"})]
    last = audit(c)[0]
    assert (last["action"], last["status"]) == ("pool-update", "started") and "+1 machine" in last["detail"] and "commentaire" in last["detail"]


def test_update_empty_comment_clears_it(api):
    c, cid = api
    assert put(c, cid, poolid="kaji-test", comment="").status_code == 200 and writes()[0]["form"] == {"poolid": "kaji-test", "comment": ""}


def test_remove_needs_confirm_then_works_in_second_call(api):
    c, cid = api
    r = put(c, cid, poolid="autre", remove_vms=[120], remove_storage=["local"])
    assert r.status_code == 400 and r.json()["detail"].startswith("Confirmation requise (renvoie la requête avec confirm=true) : ") and writes() == []
    r = put(c, cid, poolid="autre", remove_vms=[120], remove_storage=["local"], confirm=True)
    assert r.status_code == 200 and r.json()["pool"]["members"] == []
    assert writes()[0]["form"] == {"poolid": "autre", "delete": "1", "vms": "120", "storage": "local"}


def test_add_and_remove_are_two_ordered_calls(api):
    c, cid = api
    assert put(c, cid, poolid="kaji-test", add_vms=[117], remove_vms=[115], confirm=True).status_code == 200
    assert [w["form"].get("delete") for w in writes()] == [None, "1"] and STATE["pools"]["kaji-test"]["vms"] == [117]


def test_dry_run_returns_plan_and_writes_nothing(api):
    c, cid = api
    r = put(c, cid, poolid="autre", remove_vms=[120], add_vms=[117], dry_run=True)
    assert r.status_code == 200 and r.json()["dry_run"] is True and len(r.json()["calls"]) == 2 and r.json()["needs_confirm"]
    assert writes() == [] and STATE["pools"]["autre"]["vms"] == [120]


def test_moving_a_vm_from_another_pool_needs_allow_move_then_confirm(api):
    c, cid = api
    assert put(c, cid, add_vms=[120]).status_code == 409 and writes() == []                       # sans allow_move
    r = put(c, cid, add_vms=[120], allow_move=True)
    assert r.status_code == 400 and "déplacer une machine" in r.json()["detail"] and writes() == []   # sans confirm
    assert put(c, cid, add_vms=[120], allow_move=True, confirm=True).status_code == 200
    assert writes()[0]["form"]["allow-move"] == "1" and STATE["pools"]["autre"]["vms"] == [] and STATE["pools"]["vide"]["vms"] == [120]


@pytest.mark.parametrize("body", [{"add_vms": [105]}, {"remove_vms": [105]}, {"add_vms": [105], "allow_move": True, "confirm": True}])
def test_protected_vm_is_never_touched_even_confirmed(api, monkeypatch, body):
    c, cid = api
    monkeypatch.setattr("app.routers.pools.get_settings", lambda: type("S", (), {"protected_vmids": {105}})())
    r = put(c, cid, **body)
    assert r.status_code == 409 and writes() == [] and (audit(c)[0]["action"], audit(c)[0]["status"], audit(c)[0]["detail"]) == ("pool-update", "error", "machine protégée")


def test_unknown_pool_is_404_without_write(api):
    c, cid = api
    assert put(c, cid, poolid="inconnu", comment="x").status_code == 404 and writes() == []


@pytest.mark.parametrize("body,code", [
    ({}, 400), ({"confirm": True}, 400), ({"allow_move": True}, 400),
    ({"add_vms": [117], "remove_vms": [117]}, 422), ({"add_storage": ["local"], "remove_storage": ["local"]}, 422),
    ({"add_vms": [117, 117]}, 422), ({"add_vms": [99]}, 422), ({"add_vms": [1_000_000_000]}, 422), ({"add_vms": ["117"]}, 422), ({"add_vms": [True]}, 422), ({"add_vms": [1.5]}, 422),
    ({"add_storage": ["../x"]}, 422), ({"add_storage": ["a b"]}, 422), ({"add_storage": ["local", "local"]}, 422), ({"add_storage": [5]}, 422),
    ({"comment": "x" * 201}, 422), ({"comment": "a\x00"}, 422), ({"add_vms": list(range(100, 151))}, 422), ({"confirm": "true", "comment": "x"}, 422),
])
def test_invalid_update_is_refused_without_write(api, body, code):
    c, cid = api
    r = put(c, cid, **body)
    assert r.status_code == code and writes() == [] and SECRET not in r.text


def test_state_conflicts_are_409_or_404(api):
    c, cid = api
    assert put(c, cid, poolid="kaji-test", remove_vms=[117], confirm=True).status_code == 409           # pas membre
    assert put(c, cid, poolid="kaji-test", remove_storage=["local"], confirm=True).status_code == 409
    assert put(c, cid, poolid="kaji-test", add_vms=[115]).status_code == 409                               # déjà membre
    assert put(c, cid, poolid="autre", add_storage=["local"]).status_code == 409
    assert put(c, cid, add_vms=[999]).status_code == 404                                                   # machine inconnue
    assert put(c, cid, add_storage=["inconnu"]).status_code == 404                                         # stockage inconnu
    assert writes() == []


def test_proxmox_error_is_translated_audited_without_leak(api):
    c, cid = api
    STATE["fail"] = ("PUT", "/pools", 403)
    r = put(c, cid, comment="x")
    assert r.status_code == 502 and SECRET not in r.text and "10.0.0.5" not in r.text
    assert (audit(c)[0]["action"], audit(c)[0]["status"]) == ("pool-update", "error") and SECRET not in c.get("/api/audit").text


def test_second_call_failing_reports_error_after_first_applied(api):
    """Si le retrait échoue après les ajouts : erreur 502 claire, l'état relu montrera ce qui a été fait."""
    c, cid = api
    n = {"v": 0}
    orig = _handler

    def flaky(request):
        if request.method == "PUT":
            n["v"] += 1
            if n["v"] == 2:
                return _json(500)
        return orig(request)

    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(flaky)))
    r = put(c, cid, poolid="kaji-test", add_vms=[117], remove_vms=[115], confirm=True)
    assert r.status_code == 502 and STATE["pools"]["kaji-test"]["vms"] == [115, 117]
    assert audit(c)[0]["status"] == "error"


# ------------------------------------------------------------------ suppression

def test_delete_empty_pool_without_acl(api):
    c, cid = api
    r = c.delete(u(cid, "/vide?confirm=true&name=vide"))
    assert r.status_code == 200 and r.json() == {"deleted": "vide"} and "vide" not in STATE["pools"]
    assert [(w["method"], w["path"], w["query"]) for w in writes()] == [("DELETE", "/pools", {"poolid": "vide"})]
    last = audit(c)[0]
    assert (last["action"], last["status"], last["target"]) == ("pool-delete", "started", "pool/vide")


def test_delete_requires_confirm_and_exact_name_without_any_call(api):
    c, cid = api
    assert c.delete(u(cid, "/vide")).status_code == 400
    assert c.delete(u(cid, "/vide?confirm=true")).status_code == 400
    assert c.delete(u(cid, "/vide?confirm=true&name=Vide")).status_code == 400
    assert c.delete(u(cid, "/vide?confirm=true&name=vide ")).status_code == 400
    assert c.delete(u(cid, "/vide?name=vide")).status_code == 400
    assert CALLS == [] and "vide" in STATE["pools"]


def test_delete_non_empty_pool_is_refused(api):
    c, cid = api
    r = c.delete(u(cid, "/autre?confirm=true&name=autre"))
    assert r.status_code == 409 and "n'est pas vide" in r.json()["detail"] and writes() == []


def test_delete_pool_with_acl_is_refused(api):
    """Un pool qui porte des droits (ACL) : sa suppression ferait disparaître des accès (ex. ceux de Kaji sur `kaji-test`)."""
    c, cid = api
    STATE["pools"]["kaji-test"]["vms"] = []
    r = c.delete(u(cid, "/kaji-test?confirm=true&name=kaji-test"))
    assert r.status_code == 409 and "ACL" in r.json()["detail"] and writes() == []


@pytest.mark.parametrize("acl", [None, {"x": 1}, "texte"])
def test_delete_with_unreadable_acl_is_refused(api, acl):
    c, cid = api
    STATE["acl"] = acl
    assert c.delete(u(cid, "/vide?confirm=true&name=vide")).status_code == 502 and writes() == []


def test_delete_with_acl_read_error_is_refused(api):
    c, cid = api
    STATE["acl_unreadable"] = True
    r = c.delete(u(cid, "/vide?confirm=true&name=vide"))
    assert r.status_code == 502 and "Impossible de vérifier les droits" in r.json()["detail"] and writes() == []
    last = audit(c)[0]
    assert (last["action"], last["status"]) == ("pool-delete", "error") and "Impossible de vérifier" in last["detail"]


def test_delete_acl_on_other_path_does_not_block(api):
    c, cid = api
    STATE["acl"] = [{"path": "/pool/vide-autre", "roleid": "x"}, {"path": "/vms", "roleid": "y"}]
    assert c.delete(u(cid, "/vide?confirm=true&name=vide")).status_code == 200


def test_delete_unknown_pool_is_404(api):
    c, cid = api
    assert c.delete(u(cid, "/inconnu?confirm=true&name=inconnu")).status_code == 404 and writes() == []


def test_delete_proxmox_error_is_audited_without_leak(api):
    c, cid = api
    STATE["fail"] = ("DELETE", "/pools", 500)
    r = c.delete(u(cid, "/vide?confirm=true&name=vide"))
    assert r.status_code == 502 and SECRET not in r.text
    assert (audit(c)[0]["action"], audit(c)[0]["status"]) == ("pool-delete", "error")


def test_invalid_poolid_in_path_is_422_without_call(api):
    c, cid = api
    for bad in ("a b", "-x", "x" * 41):
        assert c.put(u(cid, f"/{bad}"), json={"comment": "x"}).status_code == 422
        assert c.delete(u(cid, f"/{bad}?confirm=true&name={bad}")).status_code == 422
    assert CALLS == []
