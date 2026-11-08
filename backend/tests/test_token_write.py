import re
from urllib.parse import parse_qs

import httpx
import pytest

from app import adminsession as A
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
PERM_SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": PERM_SECRET}
UUID = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
ADMIN = {"user": "admin@pve", "token_id": "kaji-admin", "secret": UUID}
ADMIN_AUTH = f"PVEAPIToken=admin@pve!kaji-admin={UUID}"
NEW_SECRET = "11111111-2222-4333-8444-555555555555"
SEEN: list[httpx.Request] = []
WRITES: list[tuple[str, str, dict]] = []
ST: dict = {}
CLOCK = {"t": 1000.0}


def fresh():
    ST.clear()
    ST["users"] = ["root@pam", "kaji@pve", "admin@pve", "bob@pve", "eve@pve"]
    ST["tokens"] = {"bob@pve": {"ci": {"privsep": 1, "comment": "intégration continue", "expire": 1900000000}, "old": {"privsep": 0, "expire": 0}},
                    "kaji@pve": {"kaji": {"privsep": 0, "expire": 0}}, "admin@pve": {"kaji-admin": {"privsep": 0}}, "eve@pve": {}}


def _handler(request: httpx.Request) -> httpx.Response:
    SEEN.append(request)
    p = request.url.path.removeprefix("/api2/json")
    if request.headers.get("authorization") != ADMIN_AUTH:
        return httpx.Response(401, json={"data": None, "message": PERM_SECRET})
    body = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    ok = lambda d=None: httpx.Response(200, json={"data": d})
    m = request.method
    if m == "GET":
        if p == "/access/permissions":
            return ok({"/pool/kaji-test": {"Permissions.Modify": 1}})
        if p == "/access/users":
            return ok([{"userid": u} for u in ST["users"]])
        mm = re.fullmatch(r"/access/users/([^/]+)/token", p)
        if mm and mm.group(1) in ST["tokens"]:
            rows = [{"tokenid": t, **v, **({"value": NEW_SECRET} if ST.get("leak_value") else {})} for t, v in ST["tokens"][mm.group(1)].items()]
            return ok(rows)
        return httpx.Response(404, json={"data": None})
    mm = re.fullmatch(r"/access/users/([^/]+)/token/([^/]+)", p)
    if not mm:
        return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})
    uid, tid = mm.groups()
    if ST.get("fail"):
        return httpx.Response(403, json={"data": None, "message": PERM_SECRET})
    if m == "POST":
        if set(body) - {"privsep", "comment", "expire"} or body.get("privsep") != "1":
            return httpx.Response(400, json={"data": None, "message": f"paramètres refusés {sorted(body)}"})
        WRITES.append((m, p, body))
        if not ST.get("noapply"):
            ST["tokens"].setdefault(uid, {})[tid] = {"privsep": 0 if ST.get("force_privsep0") else 1, "expire": int(body.get("expire", 0)), **({"comment": body["comment"]} if "comment" in body else {})}
        value = "pas-un-uuid" if ST.get("bad_value") else NEW_SECRET
        return ok({"full-tokenid": f"{uid}!{tid}", "info": {"privsep": 1}, "value": value})
    if m == "DELETE":
        WRITES.append((m, p, body))
        if not ST.get("noapply"):
            ST["tokens"].get(uid, {}).pop(tid, None)
        return ok()
    return httpx.Response(501, json={"data": None})


@pytest.fixture
def api(client, monkeypatch):
    SEEN.clear(); WRITES.clear(); fresh(); CLOCK["t"] = 1000.0
    A.sessions.clear()
    monkeypatch.setattr(A, "_now", lambda: CLOCK["t"])
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    assert client.post(f"/api/connections/{cid}/admin-session", json=ADMIN).status_code == 201
    SEEN.clear()
    yield client, cid
    A.sessions.clear()
    app.dependency_overrides.clear()


def u(cid, user="eve@pve", tail=""):
    return f"/api/connections/{cid}/access/users/{user}/tokens{tail}"


def create(c, cid, user="eve@pve", **over):
    b = {"userid": user, "tokenid": "ci", **over}
    return c.post(u(cid, user), json={"confirm": True, "type_name": f"{b['userid']}!{b['tokenid']}", **b})


def audit_text(c):
    return c.get("/api/audit").text


def test_create_returns_the_secret_once_and_never_logs_it(api):
    c, cid = api
    r = create(c, cid, comment="déploiement", expire=1900000000)
    j = r.json()
    assert r.status_code == 201 and j["created"] == "eve@pve!ci" and j["secret"] == NEW_SECRET and j["privsep"] is True and "plus jamais" in j["warning"]
    assert WRITES == [("POST", "/access/users/eve@pve/token/ci", {"privsep": "1", "comment": "déploiement", "expire": "1900000000"})]
    assert NEW_SECRET not in audit_text(c) and UUID not in audit_text(c) and "affiché une seule fois" in audit_text(c)
    assert all(q.headers["authorization"] == ADMIN_AUTH for q in SEEN)
    listed = c.get(u(cid, "eve@pve")).text
    assert NEW_SECRET not in listed and "ci" in listed                          # aucune autre route ne redonne le secret


def test_minimal_create_always_sends_privsep(api):
    c, cid = api
    assert create(c, cid).status_code == 201 and WRITES[-1][2] == {"privsep": "1"}


@pytest.mark.parametrize("privsep", [False, 0, "0", "false", None, 1, "1", "true"])      # « vrai » doit être un vrai booléen JSON (StrictBool)
def test_tokens_without_privilege_separation_are_refused(api, privsep):
    """Un token sans séparation hériterait de tous les droits de son utilisateur : jamais créé par Kaji."""
    c, cid = api
    r = create(c, cid, privsep=privsep)
    assert r.status_code == 422 and not WRITES and NEW_SECRET not in r.text


@pytest.mark.parametrize("over", [
    {"tokenid": "1abc"}, {"tokenid": "a"}, {"tokenid": "a b"}, {"tokenid": "a!b"}, {"tokenid": "a/b"}, {"tokenid": "x" * 70}, {"tokenid": ""}, {"tokenid": "ci\n"},
    {"comment": "a\nb"}, {"comment": "a" * 101}, {"comment": "a\\b"}, {"expire": -1}, {"expire": 4102444801}, {"expire": "jamais"},
])
def test_create_validated_without_any_call(api, over):
    c, cid = api
    r = create(c, cid, **over)
    assert r.status_code == 422 and not WRITES and not SEEN


@pytest.mark.parametrize("user", ["root@pam", "bob@ldap", "bob", "a b@pve", "a;b@pve", "x@pve,y@pve"])
def test_only_pve_users(api, user):
    c, cid = api
    r = c.post(f"/api/connections/{cid}/access/users/{user}/tokens", json={"userid": user, "tokenid": "ci", "confirm": True, "type_name": f"{user}!ci"})
    assert r.status_code in (404, 405, 422) and not WRITES


@pytest.mark.parametrize("user", ["kaji@pve", "admin@pve"])
def test_protected_accounts_get_no_token_and_lose_none(api, user):
    c, cid = api
    assert create(c, cid, user=user, tokenid="autre").status_code == 403
    tid = ST["tokens"][user].copy().popitem()[0]
    r = c.delete(u(cid, user, f"/{tid}"), params={"confirm": "true", "name": f"{user}!{tid}"})
    assert r.status_code == 403 and "protég" in r.json()["detail"] and not WRITES and tid in ST["tokens"][user]


def test_confirmation_and_full_id_retyped(api):
    c, cid = api
    b = {"userid": "eve@pve", "tokenid": "ci"}
    assert c.post(u(cid), json=b).status_code == 400
    for typed in (None, "", "ci", "eve@pve", "eve@pve!CI", "eve@pve!ci ", "bob@pve!ci"):
        assert c.post(u(cid), json={**b, "confirm": True, "type_name": typed}).status_code == 400
    assert c.post(u(cid), json={**b, "type_name": "eve@pve!ci"}).status_code == 400
    assert not WRITES and not SEEN


def test_body_user_must_match_the_address(api):
    c, cid = api
    r = c.post(u(cid, "eve@pve"), json={"userid": "bob@pve", "tokenid": "nouveau", "confirm": True, "type_name": "bob@pve!nouveau"})
    assert r.status_code == 422 and not WRITES and "nouveau" not in ST["tokens"]["bob@pve"]


def test_unknown_user_duplicate_and_limit(api):
    c, cid = api
    ST["users"].append("ghost@pve"); ST["users"].remove("eve@pve")
    assert create(c, cid, user="eve@pve").status_code == 404
    assert create(c, cid, user="bob@pve", tokenid="ci").status_code == 409 and not WRITES
    ST["tokens"]["bob@pve"] = {f"t{i}": {"privsep": 1} for i in range(20)}
    assert create(c, cid, user="bob@pve", tokenid="un-de-plus").status_code == 409 and not WRITES


def test_a_token_that_proxmox_created_without_separation_is_not_relayed(api):
    c, cid = api
    ST["force_privsep0"] = True
    r = create(c, cid)
    assert r.status_code == 502 and NEW_SECRET not in r.text


def test_unreadable_secret_is_never_relayed(api):
    c, cid = api
    ST["bad_value"] = True
    r = create(c, cid)
    assert r.status_code == 502 and "pas-un-uuid" not in r.text and "secret" not in r.json()


def test_not_applied_and_proxmox_errors(api):
    c, cid = api
    ST["fail"] = True
    r = create(c, cid)
    assert r.status_code == 502 and PERM_SECRET not in r.text and UUID not in r.text and NEW_SECRET not in r.text
    assert PERM_SECRET not in audit_text(c) and NEW_SECRET not in audit_text(c)


# ---------------------------------------------------------------- liste et révocation
def test_list_is_whitelisted_and_never_shows_a_value(api):
    c, cid = api
    ST["leak_value"] = True
    r = c.get(u(cid, "bob@pve"))
    assert r.status_code == 200 and NEW_SECRET not in r.text
    assert r.json() == [{"tokenid": "ci", "privsep": True, "expire": 1900000000, "comment": "intégration continue"}, {"tokenid": "old", "privsep": False, "expire": None, "comment": None}]


def test_list_truncates_long_comments(api):
    c, cid = api
    ST["tokens"]["eve@pve"] = {"long": {"privsep": 1, "comment": "x" * 300}}
    assert len(c.get(u(cid, "eve@pve")).json()[0]["comment"]) == 100


def test_revoke_token(api):
    c, cid = api
    r = c.delete(u(cid, "bob@pve", "/ci"), params={"confirm": "true", "name": "bob@pve!ci"})
    assert r.status_code == 200 and r.json() == {"revoked": "bob@pve!ci"} and WRITES == [("DELETE", "/access/users/bob@pve/token/ci", {})] and "ci" not in ST["tokens"]["bob@pve"]
    assert c.delete(u(cid, "bob@pve", "/ci"), params={"confirm": "true", "name": "bob@pve!ci"}).status_code == 404


def test_revoke_requires_confirm_and_full_id(api):
    c, cid = api
    t = u(cid, "bob@pve", "/ci")
    assert c.delete(t).status_code == 400 and c.delete(t, params={"confirm": "true"}).status_code == 400 and c.delete(t, params={"name": "bob@pve!ci"}).status_code == 400
    for typed in ("ci", "bob@pve", "BOB@pve!ci", "bob@pve!ci ", "bob@pve!old", ""):
        assert c.delete(t, params={"confirm": "true", "name": typed}).status_code == 400
    assert not WRITES and "ci" in ST["tokens"]["bob@pve"]


def test_not_applied_is_reported(api):
    c, cid = api
    ST["noapply"] = True
    assert c.delete(u(cid, "bob@pve", "/ci"), params={"confirm": "true", "name": "bob@pve!ci"}).status_code == 502
    r = create(c, cid)                                                   # Proxmox répond mais la liste ne contient pas le token : pas de faux succès, pas de secret
    assert r.status_code == 502 and "secret" not in r.json() and NEW_SECRET not in r.text


@pytest.mark.parametrize("tid", ["1x", "a b", "a!b", "x" * 70])
def test_revoke_token_name_validated(api, tid):
    c, cid = api
    assert c.delete(u(cid, "bob@pve", f"/{tid}"), params={"confirm": "true", "name": f"bob@pve!{tid}"}).status_code in (404, 405, 422) and not WRITES


def test_everything_requires_an_admin_session(api):
    c, cid = api
    c.delete(f"/api/connections/{cid}/admin-session")
    SEEN.clear()
    calls = [create(c, cid), c.get(u(cid, "bob@pve")), c.delete(u(cid, "bob@pve", "/ci"), params={"confirm": "true", "name": "bob@pve!ci"})]
    assert [r.status_code for r in calls] == [403] * 3 and not SEEN


def test_requires_login(client):
    assert client.post("/api/connections/1/access/users/bob@pve/tokens", json={}).status_code in (401, 403)
    assert client.get("/api/connections/1/access/users/bob@pve/tokens").status_code in (401, 403)


def test_audit_records_actions_without_secret(api):
    c, cid = api
    create(c, cid)
    create(c, cid, user="kaji@pve", tokenid="x1")                       # refus
    c.delete(u(cid, "bob@pve", "/ci"), params={"confirm": "true", "name": "bob@pve!ci"})
    pairs = [(a["action"], a["status"]) for a in c.get("/api/audit").json()]
    for a in (("token-create", "started"), ("token-create", "error"), ("token-revoke", "started")):
        assert a in pairs
    assert NEW_SECRET not in audit_text(c) and UUID not in audit_text(c)


def test_shape_helpers_are_defensive():
    from app.tokenwrite import secret_of, shape_tokens
    assert shape_tokens(None) == [] and shape_tokens([{"tokenid": "1x"}, "x", {"tokenid": "ok", "expire": True}, {"tokenid": "ok2", "expire": 0}]) == [
        {"tokenid": "ok", "privsep": False, "expire": None, "comment": None}, {"tokenid": "ok2", "privsep": False, "expire": None, "comment": None}]
    assert secret_of({"value": NEW_SECRET}) == NEW_SECRET
    assert secret_of({"value": "x"}) is None and secret_of(None) is None and secret_of({"value": NEW_SECRET + "x"}) is None and secret_of({"value": 5}) is None
