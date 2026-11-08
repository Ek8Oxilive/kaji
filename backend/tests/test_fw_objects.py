import re
from urllib.parse import parse_qs, unquote

import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
DIGEST = "da39a3ee5e6b4b0d3255bfef95601890afd80709"
WRITES: list[tuple[str, str, dict]] = []
READS: list[str] = []
ST: dict = {}
BASES = {"cluster": "/cluster/firewall", "guest": "/nodes/enzo/qemu/115/firewall"}
PREFIX = {"cluster": "/firewall/cluster", "guest": "/firewall/guests/enzo/qemu/115"}


def fresh():
    ST.clear()
    for b in BASES.values():
        ST[b] = {"enable": 0, "aliases": {"lan": ("192.168.1.0/24", "LAN"), "srv": ("10.0.0.5", None)}, "ipsets": {"admins": [("10.0.0.0/24", None, 0)], "vide": []}, "rules": []}
    c = ST["/cluster/firewall"]
    c["ipsets"].update({"management": [("192.168.1.0/24", None, 0)], "blacklist": []})
    c["groups"] = {"web": [], "gvide": [], "gplein": [{"pos": 0, "type": "in", "action": "ACCEPT"}]}


def _ok(d=None):
    return httpx.Response(200, json={"data": d})


def _bad(msg):
    return httpx.Response(400, json={"data": None, "message": msg})


def _handler(request: httpx.Request) -> httpx.Response:
    p = unquote(request.url.raw_path.decode().split("?")[0]).removeprefix("/api2/json")
    q = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
    body = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    m = request.method
    if m == "GET":
        READS.append(p)
    if m == "GET" and p == "/nodes":
        return _ok([{"node": "enzo"}])
    if m == "GET" and p == "/nodes/enzo/firewall/rules":
        return _ok(ST.get("node_rules", []))
    for b in BASES.values():
        if not p.startswith(b + "/") and p != b:
            continue
        s = ST[b]; rest = p[len(b):]
        if m == "GET":
            if rest == "/options":
                return _ok({"enable": s["enable"], "digest": DIGEST})
            if rest == "/rules":
                return _ok(s["rules"])
            if rest == "/aliases":
                return _ok([{"name": n, "cidr": c, "comment": cm, "digest": DIGEST} for n, (c, cm) in s["aliases"].items()])
            if rest == "/ipset":
                return _ok([{"name": n} for n in s["ipsets"]])
            mm = re.fullmatch(r"/ipset/([^/]+)", rest)
            if mm and mm.group(1) in s["ipsets"]:
                return _ok([{"cidr": c, "comment": cm, "nomatch": nm} for c, cm, nm in s["ipsets"][mm.group(1)]])
            if b == "/cluster/firewall":
                if rest == "/groups":
                    return _ok([{"group": g} for g in s["groups"]])
                mm = re.fullmatch(r"/groups/([^/]+)", rest)
                if mm and mm.group(1) in s["groups"]:
                    return _ok(s["groups"][mm.group(1)])
            return httpx.Response(404, json={"data": None})
        if ST.get("fail"):
            return httpx.Response(403, json={"data": None, "message": SECRET})
        WRITES.append((m, p, {**q, **body}))
        noapply = ST.get("noapply")
        if (m, rest) == ("POST", "/aliases"):
            if set(body) - {"name", "cidr", "comment"} or not {"name", "cidr"} <= set(body):
                return _bad("paramètres refusés")
            if not noapply:
                s["aliases"][body["name"]] = (body["cidr"], body.get("comment"))
            return _ok()
        mm = re.fullmatch(r"/aliases/([^/]+)", rest)
        if mm and m == "PUT":
            if set(body) - {"cidr", "comment", "digest"} or "cidr" not in body:
                return _bad("paramètres refusés")
            if not noapply:
                s["aliases"][mm.group(1)] = (body["cidr"], body.get("comment"))
            return _ok()
        if mm and m == "DELETE":
            if body or q:
                return _bad("paramètres refusés")
            if not noapply:
                s["aliases"].pop(mm.group(1), None)
            return _ok()
        if (m, rest) == ("POST", "/ipset"):
            if set(body) - {"name", "comment"} or "name" not in body:
                return _bad("paramètres refusés")
            if not noapply:
                s["ipsets"][body["name"]] = []
            return _ok()
        mm = re.fullmatch(r"/ipset/([^/]+)", rest)
        if mm and m == "POST":
            if set(body) - {"cidr", "comment", "nomatch"} or "cidr" not in body or body.get("nomatch", "1") not in ("0", "1"):
                return _bad("paramètres refusés")
            if not noapply:
                s["ipsets"][mm.group(1)].append((body["cidr"], body.get("comment"), int(body.get("nomatch", 0))))
            return _ok()
        if mm and m == "DELETE":
            if set(q) - {"force"} or body:
                return _bad("paramètres refusés")
            if s["ipsets"].get(mm.group(1)) and "force" not in q:
                return _bad("IPSet non vide")
            if not noapply:
                s["ipsets"].pop(mm.group(1), None)
            return _ok()
        mm = re.fullmatch(r"/ipset/([^/]+)/(.+)", rest)
        if mm and m == "DELETE":
            if q or body:
                return _bad("paramètres refusés")
            if not noapply:
                s["ipsets"][mm.group(1)] = [e for e in s["ipsets"][mm.group(1)] if e[0] != mm.group(2)]
            return _ok()
        if b == "/cluster/firewall":
            if (m, rest) == ("POST", "/groups"):
                if set(body) - {"group", "comment"} or "group" not in body:
                    return _bad("paramètres refusés")
                if not noapply:
                    s["groups"][body["group"]] = []
                return _ok()
            mm = re.fullmatch(r"/groups/([^/]+)", rest)
            if mm and m == "DELETE":
                if q or body:
                    return _bad("paramètres refusés")
                if not noapply:
                    s["groups"].pop(mm.group(1), None)
                return _ok()
    return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})


@pytest.fixture(params=["cluster", "guest"])
def api(client, request):
    WRITES.clear(); READS.clear(); fresh()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid, request.param
    app.dependency_overrides.clear()


def u(cid, scope, tail):
    return f"/api/connections/{cid}{PREFIX[scope]}{tail}"


def state(scope):
    return ST[BASES[scope]]


def audit_pairs(c):
    return [(a["action"], a["status"]) for a in c.get("/api/audit").json()]


# ---------------------------------------------------------------- alias
def test_create_alias(api):
    c, cid, sc = api
    r = c.post(u(cid, sc, "/aliases"), json={"name": "nouveau", "cidr": "10.1.0.0/16", "comment": "Réseau 1", "confirm": True})
    assert r.status_code == 201 and r.json() == {"created": "nouveau"}
    assert WRITES == [("POST", BASES[sc] + "/aliases", {"name": "nouveau", "cidr": "10.1.0.0/16", "comment": "Réseau 1"})]


@pytest.mark.parametrize("over", [
    {"name": "1abc"}, {"name": "a"}, {"name": "a b"}, {"name": "a;b"}, {"name": "x" * 70}, {"name": "../x"}, {"name": ""}, {"name": "ok\n"},
    {"cidr": "pas-une-ip"}, {"cidr": "10.0.0.0/33"}, {"cidr": "10.0.0.0/8; rm"}, {"cidr": "999.1.1.1"}, {"cidr": "1.1.1.1-1.1.1.9"}, {"cidr": "x" * 60}, {"cidr": ""},
    {"comment": "a\nb"}, {"comment": "a" * 101}, {"comment": "a\\b"},
])
def test_create_alias_validated_without_any_call(api, over):
    c, cid, sc = api
    assert c.post(u(cid, sc, "/aliases"), json={"name": "ok", "cidr": "10.0.0.1", "confirm": True, **over}).status_code == 422 and not WRITES


def test_create_alias_accepts_ipv4_ipv6_and_networks(api):
    c, cid, sc = api
    for i, cidr in enumerate(["10.0.0.1", "10.0.0.0/8", "fd00::1", "fd00::/64", "2001:db8::/32"]):
        assert c.post(u(cid, sc, "/aliases"), json={"name": f"a{i}x", "cidr": cidr, "confirm": True}).status_code == 201


def test_create_alias_needs_confirm_and_rejects_duplicates(api):
    c, cid, sc = api
    assert c.post(u(cid, sc, "/aliases"), json={"name": "nouveau", "cidr": "10.0.0.1"}).status_code == 400
    assert c.post(u(cid, sc, "/aliases"), json={"name": "lan", "cidr": "10.0.0.1", "confirm": True}).status_code == 409 and not WRITES


def test_update_alias_sends_digest_and_verifies(api):
    c, cid, sc = api
    r = c.put(u(cid, sc, "/aliases/srv"), json={"cidr": "10.0.0.9", "confirm": True, "type_name": "srv"})
    assert r.status_code == 200 and WRITES == [("PUT", BASES[sc] + "/aliases/srv", {"cidr": "10.0.0.9", "digest": DIGEST})] and state(sc)["aliases"]["srv"][0] == "10.0.0.9"


def test_update_alias_refusals(api):
    c, cid, sc = api
    assert c.put(u(cid, sc, "/aliases/srv"), json={"cidr": "10.0.0.9", "confirm": True}).status_code == 400
    for typed in (None, "", "SRV", "lan"):
        assert c.put(u(cid, sc, "/aliases/srv"), json={"cidr": "10.0.0.9", "confirm": True, "type_name": typed}).status_code == 400
    assert c.put(u(cid, sc, "/aliases/inconnu"), json={"cidr": "10.0.0.9", "confirm": True, "type_name": "inconnu"}).status_code == 404
    assert c.put(u(cid, sc, "/aliases/srv"), json={"cidr": "10.0.0.5", "confirm": True, "type_name": "srv"}).status_code == 422       # rien ne change
    assert c.put(u(cid, sc, "/aliases/srv"), json={"cidr": "nimporte quoi", "confirm": True, "type_name": "srv"}).status_code == 422
    assert not WRITES


def test_delete_alias(api):
    c, cid, sc = api
    assert c.delete(u(cid, sc, "/aliases/srv")).status_code == 400
    assert c.delete(u(cid, sc, "/aliases/srv"), params={"confirm": "true", "typed": "autre"}).status_code == 400
    r = c.delete(u(cid, sc, "/aliases/srv"), params={"confirm": "true", "typed": "srv"})
    assert r.status_code == 200 and WRITES == [("DELETE", BASES[sc] + "/aliases/srv", {})] and "srv" not in state(sc)["aliases"]
    assert c.delete(u(cid, sc, "/aliases/srv"), params={"confirm": "true", "typed": "srv"}).status_code == 404


@pytest.mark.parametrize("ref", ["lan", "dc/lan", "guest/lan", "10.0.0.1,lan"])
def test_an_alias_named_by_a_rule_is_never_deleted(api, ref):
    c, cid, sc = api
    state(sc)["rules"] = [{"pos": 3, "type": "in", "action": "ACCEPT", "source": ref}]
    r = c.delete(u(cid, sc, "/aliases/lan"), params={"confirm": "true", "typed": "lan"})
    assert r.status_code == 409 and "3" in r.json()["detail"] and not WRITES


def test_alias_in_a_live_firewall_needs_explicit_unlock_to_change(api):
    c, cid, sc = api
    state(sc)["enable"] = 1
    state(sc)["rules"] = [{"pos": 2, "type": "in", "action": "ACCEPT", "dest": "dc/lan" if sc == "guest" else "lan"}]
    b = {"cidr": "10.9.9.0/24", "confirm": True, "type_name": "lan"}
    r = c.put(u(cid, sc, "/aliases/lan"), json=b)
    assert r.status_code == 409 and "ACTIF" in r.json()["detail"] and "2" in r.json()["detail"] and not WRITES
    assert c.put(u(cid, sc, "/aliases/lan"), json={**b, "acknowledge_live": True}).status_code == 200 and state(sc)["aliases"]["lan"][0] == "10.9.9.0/24"


def test_alias_referenced_but_firewall_disabled_is_inert(api):
    c, cid, sc = api
    state(sc)["rules"] = [{"pos": 2, "type": "in", "action": "ACCEPT", "source": "lan"}]
    assert c.put(u(cid, sc, "/aliases/lan"), json={"cidr": "10.9.9.0/24", "confirm": True, "type_name": "lan"}).status_code == 200


# ---------------------------------------------------------------- IPSet
def test_ipset_lifecycle(api):
    c, cid, sc = api
    assert c.post(u(cid, sc, "/ipsets"), json={"name": "nouveau", "comment": "Test", "confirm": True}).status_code == 201
    assert WRITES[-1] == ("POST", BASES[sc] + "/ipset", {"name": "nouveau", "comment": "Test"})
    assert c.post(u(cid, sc, "/ipsets"), json={"name": "nouveau", "confirm": True}).status_code == 409
    assert c.post(u(cid, sc, "/ipsets"), json={"name": "x y", "confirm": True}).status_code == 422
    assert c.delete(u(cid, sc, "/ipsets/nouveau"), params={"confirm": "true", "typed": "nouveau"}).status_code == 200 and "nouveau" not in state(sc)["ipsets"]


def test_ipset_entries_add_and_remove(api):
    c, cid, sc = api
    r = c.post(u(cid, sc, "/ipsets/vide/entries"), json={"cidr": "192.0.2.0/24", "comment": "doc", "nomatch": True, "confirm": True})
    assert r.status_code == 201 and WRITES[-1] == ("POST", BASES[sc] + "/ipset/vide", {"cidr": "192.0.2.0/24", "comment": "doc", "nomatch": "1"})
    assert c.post(u(cid, sc, "/ipsets/vide/entries"), json={"cidr": "lan", "confirm": True}).status_code == 201                 # référence à un alias
    assert c.post(u(cid, sc, "/ipsets/vide/entries"), json={"cidr": "192.0.2.0/24", "confirm": True}).status_code == 409
    r = c.delete(u(cid, sc, "/ipsets/vide/entries"), params={"cidr": "192.0.2.0/24", "confirm": "true", "typed": "192.0.2.0/24"})
    assert r.status_code == 200 and WRITES[-1] == ("DELETE", BASES[sc] + "/ipset/vide/192.0.2.0/24", {}) and [e[0] for e in state(sc)["ipsets"]["vide"]] == ["lan"]


@pytest.mark.parametrize("cidr", ["pas une ip", "10.0.0.0/40", "a;b", "../x", "1.1.1.1,2.2.2.2", "", "x" * 80, "10.0.0.1\n"])
def test_entry_validated_without_any_call(api, cidr):
    c, cid, sc = api
    assert c.post(u(cid, sc, "/ipsets/vide/entries"), json={"cidr": cidr, "confirm": True}).status_code == 422 and not WRITES
    assert c.delete(u(cid, sc, "/ipsets/vide/entries"), params={"cidr": cidr, "confirm": "true", "typed": cidr}).status_code == 422 and not WRITES


def test_entry_removal_requires_confirm_and_retyped_value(api):
    c, cid, sc = api
    p = {"cidr": "10.0.0.0/24"}
    assert c.delete(u(cid, sc, "/ipsets/admins/entries"), params=p).status_code == 400
    assert c.delete(u(cid, sc, "/ipsets/admins/entries"), params={**p, "confirm": "true"}).status_code == 400
    assert c.delete(u(cid, sc, "/ipsets/admins/entries"), params={**p, "confirm": "true", "typed": "10.0.0.0/8"}).status_code == 400
    assert c.delete(u(cid, sc, "/ipsets/admins/entries"), params={"cidr": "10.9.9.9", "confirm": "true", "typed": "10.9.9.9"}).status_code == 404 and not WRITES


def test_non_empty_ipset_needs_delete_members(api):
    c, cid, sc = api
    p = {"confirm": "true", "typed": "admins"}
    r = c.delete(u(cid, sc, "/ipsets/admins"), params=p)
    assert r.status_code == 409 and "delete_members" in r.json()["detail"] and not WRITES
    r = c.delete(u(cid, sc, "/ipsets/admins"), params={**p, "delete_members": "true"})
    assert r.status_code == 200 and r.json()["members_deleted"] == 1 and WRITES == [("DELETE", BASES[sc] + "/ipset/admins", {"force": "1"})]


@pytest.mark.parametrize("ref", ["+admins", "+dc/admins", "+guest/admins", "10.0.0.1,+admins"])
def test_an_ipset_named_by_a_rule_is_never_deleted(api, ref):
    c, cid, sc = api
    state(sc)["rules"] = [{"pos": 5, "type": "in", "action": "DROP", "source": ref}]
    r = c.delete(u(cid, sc, "/ipsets/admins"), params={"confirm": "true", "typed": "admins", "delete_members": "true"})
    assert r.status_code == 409 and "5" in r.json()["detail"] and not WRITES


def test_entry_of_a_live_ipset_needs_explicit_unlock(api):
    c, cid, sc = api
    state(sc)["enable"] = 1
    state(sc)["rules"] = [{"pos": 1, "type": "in", "action": "ACCEPT", "source": "+admins"}]
    b = {"cidr": "10.7.7.7", "confirm": True}
    assert c.post(u(cid, sc, "/ipsets/admins/entries"), json=b).status_code == 409 and not WRITES
    assert c.delete(u(cid, sc, "/ipsets/admins/entries"), params={"cidr": "10.0.0.0/24", "confirm": "true", "typed": "10.0.0.0/24"}).status_code == 409 and not WRITES
    assert c.post(u(cid, sc, "/ipsets/admins/entries"), json={**b, "acknowledge_live": True}).status_code == 201
    assert c.delete(u(cid, sc, "/ipsets/admins/entries"), params={"cidr": "10.0.0.0/24", "confirm": "true", "typed": "10.0.0.0/24", "acknowledge_live": "true"}).status_code == 200


@pytest.mark.parametrize("name", ["management", "blacklist"])
def test_builtin_ipsets_are_always_locked(api, name):
    """`management` (les adresses autorisées à administrer) et `blacklist` servent sans qu'une règle les nomme : verrou même pare-feu éteint."""
    c, cid, sc = api
    if sc == "guest":
        pytest.skip("ensembles intégrés : niveau datacenter seulement")
    b = {"cidr": "10.7.7.7", "confirm": True}
    assert c.post(u(cid, sc, f"/ipsets/{name}/entries"), json=b).status_code == 409 and "intégré" in c.post(u(cid, sc, f"/ipsets/{name}/entries"), json=b).json()["detail"] and not WRITES
    assert c.post(u(cid, sc, f"/ipsets/{name}/entries"), json={**b, "acknowledge_live": True}).status_code == 201


def test_unknown_ipset_and_name_paths(api):
    c, cid, sc = api
    assert c.post(u(cid, sc, "/ipsets/inconnu/entries"), json={"cidr": "10.0.0.1", "confirm": True}).status_code == 404
    assert c.delete(u(cid, sc, "/ipsets/inconnu"), params={"confirm": "true", "typed": "inconnu"}).status_code == 404
    for bad in ("1abc", "a b", "x" * 70):
        assert c.delete(u(cid, sc, f"/ipsets/{bad}"), params={"confirm": "true", "typed": bad}).status_code in (404, 422)
    assert not WRITES


# ---------------------------------------------------------------- groupes (datacenter seulement)
def test_groups(api):
    c, cid, sc = api
    if sc == "guest":
        assert c.post(u(cid, sc, "/groups"), json={"name": "web2", "confirm": True}).status_code in (404, 405)
        return
    assert c.post(u(cid, sc, "/groups"), json={"name": "web2", "comment": "Web", "confirm": True}).status_code == 201 and WRITES[-1] == ("POST", "/cluster/firewall/groups", {"group": "web2", "comment": "Web"})
    assert c.post(u(cid, sc, "/groups"), json={"name": "web", "confirm": True}).status_code == 409
    for bad in ("x" * 19, "1ab", "a b", "a"):
        assert c.post(u(cid, sc, "/groups"), json={"name": bad, "confirm": True}).status_code == 422
    assert c.post(u(cid, sc, "/groups"), json={"name": "x" * 18, "confirm": True}).status_code == 201                     # 18 caractères : limite de Proxmox


def test_delete_group_only_when_unused_and_empty(api):
    c, cid, sc = api
    if sc == "guest":
        pytest.skip("groupes : niveau datacenter seulement")
    p = {"confirm": "true", "typed": "gvide"}
    assert c.delete(u(cid, sc, "/groups/gvide")).status_code == 400 and c.delete(u(cid, sc, "/groups/gvide"), params={**p, "typed": "autre"}).status_code == 400
    r = c.delete(u(cid, sc, "/groups/gplein"), params={"confirm": "true", "typed": "gplein"})
    assert r.status_code == 409 and "non vide" in r.json()["detail"] and not WRITES
    ST["node_rules"] = [{"pos": 4, "type": "group", "action": "gvide"}]
    r = c.delete(u(cid, sc, "/groups/gvide"), params=p)
    assert r.status_code == 409 and "4" in r.json()["detail"] and not WRITES
    ST["node_rules"] = []
    assert c.delete(u(cid, sc, "/groups/gvide"), params=p).status_code == 200 and "gvide" not in state(sc)["groups"]


def test_object_of_a_live_firewall_is_found_through_node_and_group_rules(api):
    c, cid, sc = api
    if sc == "guest":
        pytest.skip("niveau datacenter seulement")
    state(sc)["enable"] = 1
    ST["node_rules"] = [{"pos": 9, "type": "in", "action": "ACCEPT", "source": "lan"}]
    r = c.put(u(cid, sc, "/aliases/lan"), json={"cidr": "10.9.9.0/24", "confirm": True, "type_name": "lan"})
    assert r.status_code == 409 and "9" in r.json()["detail"] and not WRITES


# ---------------------------------------------------------------- Proxmox, audit
def test_not_applied_and_errors(api):
    c, cid, sc = api
    ST["noapply"] = True
    assert c.post(u(cid, sc, "/aliases"), json={"name": "nouveau", "cidr": "10.0.0.1", "confirm": True}).status_code == 502
    assert c.post(u(cid, sc, "/ipsets"), json={"name": "nouveau", "confirm": True}).status_code == 502
    assert c.post(u(cid, sc, "/ipsets/vide/entries"), json={"cidr": "10.0.0.1", "confirm": True}).status_code == 502
    assert c.delete(u(cid, sc, "/aliases/srv"), params={"confirm": "true", "typed": "srv"}).status_code == 502
    ST.pop("noapply"); ST["fail"] = True
    r = c.post(u(cid, sc, "/aliases"), json={"name": "autre", "cidr": "10.0.0.1", "confirm": True})
    assert r.status_code == 502 and SECRET not in r.text and SECRET not in c.get("/api/audit").text


def test_audit_records_actions(api):
    c, cid, sc = api
    c.post(u(cid, sc, "/aliases"), json={"name": "nouveau", "cidr": "10.0.0.1", "confirm": True})
    c.post(u(cid, sc, "/aliases"), json={"name": "lan", "cidr": "10.0.0.1", "confirm": True})                       # doublon
    c.delete(u(cid, sc, "/aliases/nouveau"), params={"confirm": "true", "typed": "nouveau"})
    pairs = audit_pairs(c)
    for a in (("fw-alias-create", "started"), ("fw-alias-create", "error"), ("fw-alias-delete", "started")):
        assert a in pairs


def test_requires_login(client):
    for method, tail in (("post", "/cluster/aliases"), ("put", "/cluster/aliases/x"), ("delete", "/cluster/ipsets/x"), ("post", "/cluster/ipsets/x/entries"), ("post", "/guests/enzo/qemu/115/aliases")):
        assert getattr(client, method)(f"/api/connections/1/firewall{tail}").status_code in (401, 403, 422)
    assert client.post("/api/connections/1/firewall/cluster/aliases", json={}).status_code == 401


# ---------------------------------------------------------------- trous trouvés par les mutations
@pytest.mark.parametrize("field,value", [("confirm", "true"), ("confirm", 1), ("acknowledge_live", "true"), ("acknowledge_live", 1), ("nomatch", "1"), ("nomatch", "true")])
def test_flags_must_be_real_booleans(api, field, value):
    """Un « true » en texte ou un 1 n'est pas une confirmation : booléens stricts."""
    c, cid, sc = api
    b = {"cidr": "10.7.7.7", "confirm": True, field: value}
    assert c.post(u(cid, sc, "/ipsets/vide/entries"), json=b).status_code == 422 and not WRITES


def test_references_unit():
    from app.fwobjects import is_live, references
    assert references([{"pos": 1, "type": "in", "action": "web"}, {"pos": 2, "type": "group", "action": "web"}], "group", "web") == [2]
    assert references([{"pos": 1, "source": "+a", "dest": "b"}], "alias", "a") == [] and references([{"pos": 1, "source": "+a", "dest": "b"}], "alias", "b") == [1]
    assert references([{"pos": 1, "source": "+a", "dest": "b"}], "ipset", "b") == [] and references([{"pos": 1, "source": "+a"}], "ipset", "a") == [1]
    assert is_live("alias", "x", [], True) is False and is_live("alias", "x", [1], False) is False and is_live("alias", "x", [1], True) is True
    assert is_live("ipset", "management", [], False) is True and is_live("ipset", "blacklist", [], False) is True and is_live("ipset", "admins", [], True) is False


def test_an_active_firewall_does_not_lock_objects_nobody_uses(api):
    c, cid, sc = api
    state(sc)["enable"] = 1
    assert c.put(u(cid, sc, "/aliases/srv"), json={"cidr": "10.0.0.9", "confirm": True, "type_name": "srv"}).status_code == 200
    assert c.post(u(cid, sc, "/ipsets/vide/entries"), json={"cidr": "10.7.7.7", "confirm": True}).status_code == 201


def test_group_rules_are_searched_for_references(api):
    c, cid, sc = api
    if sc == "guest":
        pytest.skip("niveau datacenter seulement")
    state(sc)["groups"]["web"] = [{"pos": 0, "type": "in", "action": "ACCEPT", "source": "lan"}]
    r = c.delete(u(cid, sc, "/aliases/lan"), params={"confirm": "true", "typed": "lan"})
    assert r.status_code == 409 and "0" in r.json()["detail"] and not WRITES


@pytest.mark.parametrize("name,members", [("management", True), ("blacklist", False)])
def test_deleting_a_builtin_ipset_is_locked(api, name, members):
    c, cid, sc = api
    if sc == "guest":
        pytest.skip("ensembles intégrés : niveau datacenter seulement")
    p = {"confirm": "true", "typed": name, **({"delete_members": "true"} if members else {})}
    r = c.delete(u(cid, sc, f"/ipsets/{name}"), params=p)
    assert r.status_code == 409 and "intégré" in r.json()["detail"] and not WRITES
    assert c.delete(u(cid, sc, f"/ipsets/{name}"), params={**p, "acknowledge_live": "true"}).status_code == 200


def test_guest_level_reads_only_its_own_rules(api):
    """Au niveau machine, on ne relit ni les groupes ni les règles des nœuds du datacenter."""
    c, cid, sc = api
    if sc == "cluster":
        pytest.skip("niveau machine seulement")
    c.put(u(cid, sc, "/aliases/srv"), json={"cidr": "10.0.0.9", "confirm": True, "type_name": "srv"})
    assert not [r for r in READS if r.startswith("/cluster/") or r.startswith("/nodes/enzo/firewall") or r == "/nodes"]
