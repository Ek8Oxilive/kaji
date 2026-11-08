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
USER_PW = "mot-de-passe-du-nouvel-utilisateur"
SEEN: list[httpx.Request] = []
WRITES: list[tuple[str, str, dict]] = []
ST: dict = {}
CLOCK = {"t": 1000.0}

ROLES = [{"roleid": "Administrator", "privs": "Permissions.Modify,User.Modify"}, {"roleid": "PVEAuditor", "privs": "Sys.Audit,VM.Audit"},
         {"roleid": "Evil", "privs": "User.Modify"}, {"roleid": "Mod", "privs": "Permissions.Modify"}]


def fresh():
    ST.clear()
    ST["users"] = {"root@pam": {"enable": 1, "expire": 0}, "kaji@pve": {"enable": 1, "expire": 0}, "admin@pve": {"enable": 1, "expire": 0},
                   "bob@pve": {"enable": 1, "expire": 0, "comment": "Bob"}, "eve@pve": {"enable": 0, "expire": 0}, "carl@pve": {"enable": 1, "expire": 0}}
    ST["groups"] = {"staff": ["bob@pve"], "vide": [], "admins": [], "evilg": [], "modg": [], "sysg": [], "ghostrole": [], "ok": [], "seulmembres": ["carl@pve"]}
    ST["acl"] = [{"path": "/", "type": "group", "ugid": "admins", "roleid": "Administrator", "propagate": 1},
                 {"path": "/pool/kaji-test", "type": "group", "ugid": "evilg", "roleid": "Evil", "propagate": 1},
                 {"path": "/vms/115", "type": "group", "ugid": "modg", "roleid": "Mod", "propagate": 1},
                 {"path": "/access/groups", "type": "group", "ugid": "sysg", "roleid": "PVEAuditor", "propagate": 1},
                 {"path": "/pool/x", "type": "group", "ugid": "ghostrole", "roleid": "RoleInconnu", "propagate": 1},
                 {"path": "/pool/kaji-test", "type": "group", "ugid": "ok", "roleid": "PVEAuditor", "propagate": 1},
                 {"path": "/pool/kaji-test", "type": "group", "ugid": "staff", "roleid": "PVEAuditor", "propagate": 1},
                 {"path": "/pool/kaji-test", "type": "user", "ugid": "bob@pve", "roleid": "PVEAuditor", "propagate": 1},
                 {"path": "/pool/kaji-test", "type": "token", "ugid": "bob@pve!ci", "roleid": "PVEAuditor", "propagate": 1}]


def _groups_of(uid):
    return sorted(g for g, members in ST["groups"].items() if uid in members)


def _strict(body, allowed):
    return httpx.Response(400, json={"data": None, "message": f"paramètres refusés {sorted(set(body) - allowed)}"}) if set(body) - allowed else None


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
            return ok([{"userid": u, "enable": v["enable"], "expire": v["expire"], "realm-type": "pam" if u.endswith("@pam") else "pve"} for u, v in ST["users"].items()])
        if p == "/access/groups":
            return ok([{"groupid": g, "users": ",".join(mm)} for g, mm in ST["groups"].items()])
        if p == "/access/acl":
            return ok(ST["acl"])
        if p == "/access/roles":
            return ok([dict(r, privs="") if (ST.get("admin_listed_empty") and r["roleid"] == "Administrator") else r for r in ROLES])
        mm = re.fullmatch(r"/access/users/([^/]+)", p)
        if mm and mm.group(1) in ST["users"]:
            u = ST["users"][mm.group(1)]
            return ok({"enable": u["enable"], "expire": u["expire"], "groups": _groups_of(mm.group(1)), "tokens": {"ci": {"privsep": 1}} if mm.group(1) == "bob@pve" else {}})
        return httpx.Response(404, json={"data": None})
    if ST.get("fail"):
        return httpx.Response(403, json={"data": None, "message": PERM_SECRET})
    if (m, p) == ("POST", "/access/users"):
        if (e := _strict(body, {"userid", "comment", "enable", "expire", "password"})) or "userid" not in body or body.get("enable", "1") not in ("0", "1"):
            return e or httpx.Response(400, json={"data": None})
        WRITES.append((m, p, body))
        if not ST.get("noapply"):
            ST["users"][body["userid"]] = {"enable": int(body.get("enable", 1)), "expire": int(body.get("expire", 0))}
        return ok()
    mm = re.fullmatch(r"/access/users/([^/]+)", p)
    if mm and m == "PUT":
        if (e := _strict(body, {"enable", "comment", "expire", "groups", "append"})) or body.get("enable", "1") not in ("0", "1") or body.get("append", "1") != "1":
            return e or httpx.Response(400, json={"data": None})
        WRITES.append((m, p, body))
        uid = mm.group(1)
        if not ST.get("noapply"):
            if "enable" in body:
                ST["users"][uid]["enable"] = int(body["enable"])
            if "groups" in body:
                wanted = [g for g in body["groups"].split(",") if g]
                if body.get("append"):
                    wanted = sorted(set(_groups_of(uid)) | set(wanted))
                for g in ST["groups"]:
                    ST["groups"][g] = [x for x in ST["groups"][g] if x != uid] + ([uid] if g in wanted else [])
        return ok()
    if mm and m == "DELETE":
        WRITES.append((m, p, body))
        if not ST.get("noapply"):
            ST["users"].pop(mm.group(1), None)
        return ok()
    if (m, p) == ("POST", "/access/groups"):
        if (e := _strict(body, {"groupid", "comment"})) or "groupid" not in body:
            return e or httpx.Response(400, json={"data": None})
        WRITES.append((m, p, body))
        if not ST.get("noapply"):
            ST["groups"][body["groupid"]] = []
        return ok()
    mm = re.fullmatch(r"/access/groups/([^/]+)", p)
    if mm and m == "DELETE":
        WRITES.append((m, p, body))
        if not ST.get("noapply"):
            ST["groups"].pop(mm.group(1), None)
        return ok()
    return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})


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


def u(cid, tail):
    return f"/api/connections/{cid}/access{tail}"


def audit_text(c):
    return c.get("/api/audit").text


def create(c, cid, **over):
    b = {"userid": "new@pve", **over}
    return c.post(u(cid, "/users"), json={"confirm": True, "type_name": b["userid"], **b})


def member(c, cid, userid="eve@pve", group="ok", action="add", **over):
    return c.put(u(cid, f"/users/{userid}/groups"), json={"group": group, "action": action, "confirm": True, "type_name": userid, **over})


# ---------------------------------------------------------------- créer un utilisateur
def test_create_user_exact_params_and_password_never_leaks(api):
    c, cid = api
    r = create(c, cid, comment="Nouvel utilisateur", enable=False, expire=1900000000, password=USER_PW)
    assert r.status_code == 201 and r.json() == {"created": "new@pve"}
    assert WRITES == [("POST", "/access/users", {"userid": "new@pve", "enable": "0", "comment": "Nouvel utilisateur", "expire": "1900000000", "password": USER_PW})]
    assert USER_PW not in r.text and USER_PW not in audit_text(c) and UUID not in audit_text(c) and "mot de passe défini" in audit_text(c)
    assert all(q.headers["authorization"] == ADMIN_AUTH for q in SEEN)


def test_create_user_minimal_has_no_password_param(api):
    c, cid = api
    assert create(c, cid).status_code == 201 and WRITES[-1][2] == {"userid": "new@pve", "enable": "1"}


@pytest.mark.parametrize("over", [
    {"userid": "bob@pam"}, {"userid": "bob@ldap"}, {"userid": "bob"}, {"userid": "@pve"}, {"userid": "a b@pve"}, {"userid": "a;b@pve"}, {"userid": "root@pam"},
    {"userid": "x" * 70 + "@pve"}, {"userid": "bob@pve\n"}, {"userid": "a@pve,b@pve"},
    {"password": "court"}, {"password": "x" * 129}, {"password": "mot de passe\nsur deux lignes"},
    {"comment": "a" * 101}, {"comment": "ligne1\nligne2"}, {"comment": "a\\b"}, {"expire": -1}, {"expire": 4102444801}, {"expire": "demain"},
])
def test_create_user_validated_without_any_call(api, over):
    c, cid = api
    r = create(c, cid, **over)
    assert r.status_code == 422 and not WRITES and not SEEN
    assert USER_PW not in r.text


def test_create_user_confirmation_and_duplicates(api):
    c, cid = api
    b = {"userid": "new@pve"}
    assert c.post(u(cid, "/users"), json=b).status_code == 400
    for typed in (None, "", "new@pve ", "NEW@pve", "bob@pve"):
        assert c.post(u(cid, "/users"), json={**b, "confirm": True, "type_name": typed}).status_code == 400
    assert not WRITES and not SEEN
    assert create(c, cid, userid="bob@pve").status_code == 409 and not WRITES


@pytest.mark.parametrize("uid", ["kaji@pve", "admin@pve"])
def test_create_cannot_target_protected_accounts(api, uid):
    c, cid = api
    r = create(c, cid, userid=uid)
    assert r.status_code == 403 and "protég" in r.json()["detail"] and not WRITES


# ---------------------------------------------------------------- activer, désactiver, modifier
def test_disable_and_enable(api):
    c, cid = api
    for enable in (False, True):
        r = c.put(u(cid, "/users/bob@pve"), json={"enable": enable, "confirm": True, "type_name": "bob@pve"})
        assert r.status_code == 200 and WRITES[-1] == ("PUT", "/access/users/bob@pve", {"enable": "1" if enable else "0"})
        assert ST["users"]["bob@pve"]["enable"] == int(enable)


def test_update_comment_and_expire(api):
    c, cid = api
    assert c.put(u(cid, "/users/bob@pve"), json={"comment": "Robert", "expire": 1900000000, "confirm": True, "type_name": "bob@pve"}).status_code == 200
    assert WRITES[-1][2] == {"comment": "Robert", "expire": "1900000000"}


@pytest.mark.parametrize("uid", ["kaji@pve", "admin@pve"])
def test_protected_users_cannot_be_modified_or_deleted(api, uid):
    c, cid = api
    assert c.put(u(cid, f"/users/{uid}"), json={"enable": False, "confirm": True, "type_name": uid}).status_code == 403
    assert c.delete(u(cid, f"/users/{uid}"), params={"confirm": "true", "name": uid}).status_code == 403
    assert member(c, cid, userid=uid).status_code == 403 and not WRITES


def test_update_refusals(api):
    c, cid = api
    assert c.put(u(cid, "/users/bob@pve"), json={"confirm": True, "type_name": "bob@pve"}).status_code == 422                  # rien à modifier
    assert c.put(u(cid, "/users/bob@pve"), json={"enable": False}).status_code == 400
    assert c.put(u(cid, "/users/ghost@pve"), json={"enable": False, "confirm": True, "type_name": "ghost@pve"}).status_code == 404
    assert c.put(u(cid, "/users/root@pam"), json={"enable": False, "confirm": True, "type_name": "root@pam"}).status_code == 422     # pas du realm pve
    assert c.put(u(cid, "/users/bob@pve"), json={"enable": "peut-être", "confirm": True, "type_name": "bob@pve"}).status_code == 422
    assert not WRITES


# ---------------------------------------------------------------- supprimer
def test_delete_user_requires_confirm_and_exact_name(api):
    c, cid = api
    assert c.delete(u(cid, "/users/eve@pve")).status_code == 400
    assert c.delete(u(cid, "/users/eve@pve"), params={"confirm": "true"}).status_code == 400
    assert c.delete(u(cid, "/users/eve@pve"), params={"name": "eve@pve"}).status_code == 400
    for typed in ("EVE@pve", "eve@pve ", "bob@pve", ""):
        assert c.delete(u(cid, "/users/eve@pve"), params={"confirm": "true", "name": typed}).status_code == 400
    assert not WRITES and "eve@pve" in ST["users"]


def test_delete_user(api):
    c, cid = api
    r = c.delete(u(cid, "/users/eve@pve"), params={"confirm": "true", "name": "eve@pve"})
    assert r.status_code == 200 and r.json() == {"deleted": "eve@pve"} and WRITES == [("DELETE", "/access/users/eve@pve", {})] and "eve@pve" not in ST["users"]
    assert c.delete(u(cid, "/users/eve@pve"), params={"confirm": "true", "name": "eve@pve"}).status_code == 404


@pytest.mark.parametrize("uid", ["root@pam", "bob@ldap", "bob", "a b@pve"])
def test_delete_only_pve_users(api, uid):
    c, cid = api
    assert c.delete(u(cid, f"/users/{uid}"), params={"confirm": "true", "name": uid}).status_code in (404, 405, 422) and not WRITES


def test_impact_is_read_only(api):
    c, cid = api
    r = c.get(u(cid, "/users/bob@pve/impact"))
    assert r.status_code == 200 and r.json() == {"userid": "bob@pve", "protected": False, "groups": ["staff"], "acl_entries": 2, "tokens": ["ci"]} and not WRITES
    assert c.get(u(cid, "/users/kaji@pve/impact")).json()["protected"] is True


# ---------------------------------------------------------------- appartenance
def test_add_to_safe_group(api):
    c, cid = api
    r = member(c, cid)
    assert r.status_code == 200 and WRITES == [("PUT", "/access/users/eve@pve", {"groups": "ok", "append": "1"})] and "eve@pve" in ST["groups"]["ok"]


@pytest.mark.parametrize("group", ["admins", "evilg", "modg", "sysg", "ghostrole"])
def test_adding_to_a_group_with_admin_rights_is_refused(api, group):
    c, cid = api
    r = member(c, cid, group=group)
    assert r.status_code == 403 and "modifier les droits" in r.json()["detail"] and not WRITES and "eve@pve" not in ST["groups"][group]


def test_administrator_group_is_refused_by_role_name_even_if_listed_without_privileges(api):
    """Défense en profondeur : le nom du rôle suffit, sans dépendre de la liste des privilèges renvoyée par Proxmox."""
    c, cid = api
    ST["admin_listed_empty"] = True
    assert member(c, cid, group="admins").status_code == 403 and not WRITES


def test_protected_reason_unit():
    """`root@pam` n'atteint jamais ce code par l'API (le format exige @pve) : on le vérifie ici, la protection reste valable si le format change."""
    from app.userwrite import protected_reason
    assert protected_reason("root@pam", "kaji@pve", "admin@pve") and protected_reason("kaji@pve", "kaji@pve", "admin@pve")
    assert protected_reason("admin@pve", "kaji@pve", "admin@pve") and protected_reason("bob@pve", "kaji@pve", "admin@pve") is None


def test_removing_from_a_dangerous_group_is_allowed(api):
    c, cid = api
    ST["groups"]["admins"] = ["bob@pve"]
    assert member(c, cid, userid="bob@pve", group="admins", action="remove").status_code == 200 and "bob@pve" not in ST["groups"]["admins"]


def test_remove_keeps_other_groups(api):
    c, cid = api
    ST["groups"]["ok"] = ["bob@pve"]
    assert member(c, cid, userid="bob@pve", group="staff", action="remove").status_code == 200
    assert WRITES[-1] == ("PUT", "/access/users/bob@pve", {"groups": "ok"}) and _groups_of_state("bob@pve") == ["ok"]


def _groups_of_state(uid):
    return sorted(g for g, mm in ST["groups"].items() if uid in mm)


def test_remove_last_group_sends_empty_list(api):
    c, cid = api
    assert member(c, cid, userid="bob@pve", group="staff", action="remove").status_code == 200 and WRITES[-1][2] == {"groups": ""}


def test_membership_conflicts_and_unknowns(api):
    c, cid = api
    assert member(c, cid, userid="bob@pve", group="staff").status_code == 409
    assert member(c, cid, userid="eve@pve", group="staff", action="remove").status_code == 404
    assert member(c, cid, userid="ghost@pve").status_code == 404
    assert member(c, cid, group="ghostgroup").status_code == 404 and not WRITES


@pytest.mark.parametrize("over", [{"action": "toggle"}, {"action": "add,remove"}, {"group": "a b"}, {"group": "a,b"}, {"group": ""}, {"group": "../x"}])
def test_membership_validated(api, over):
    c, cid = api
    assert member(c, cid, **over).status_code == 422 and not WRITES


def test_membership_confirmation(api):
    c, cid = api
    assert member(c, cid, confirm=False).status_code == 400 and member(c, cid, type_name="bob@pve").status_code == 400 and not WRITES


# ---------------------------------------------------------------- groupes
def test_create_group(api):
    c, cid = api
    r = c.post(u(cid, "/groups"), json={"groupid": "devs", "comment": "Équipe", "confirm": True, "type_name": "devs"})
    assert r.status_code == 201 and WRITES == [("POST", "/access/groups", {"groupid": "devs", "comment": "Équipe"})] and "devs" in ST["groups"]
    assert c.post(u(cid, "/groups"), json={"groupid": "devs", "confirm": True, "type_name": "devs"}).status_code == 409


@pytest.mark.parametrize("over", [{"groupid": "a b"}, {"groupid": "a,b"}, {"groupid": ""}, {"groupid": "-x"}, {"groupid": "x" * 70}, {"comment": "a\nb"}])
def test_create_group_validated(api, over):
    c, cid = api
    b = {"groupid": "devs", **over}
    assert c.post(u(cid, "/groups"), json={**b, "confirm": True, "type_name": b["groupid"]}).status_code == 422 and not WRITES


def test_delete_empty_group_only(api):
    c, cid = api
    assert c.delete(u(cid, "/groups/vide")).status_code == 400
    assert c.delete(u(cid, "/groups/vide"), params={"confirm": "true", "name": "autre"}).status_code == 400
    r = c.delete(u(cid, "/groups/staff"), params={"confirm": "true", "name": "staff"})
    assert r.status_code == 409 and "encore utilisé" in r.json()["detail"] and not WRITES                       # un membre et une entrée d'ACL
    ST["groups"]["staff"] = []
    assert c.delete(u(cid, "/groups/staff"), params={"confirm": "true", "name": "staff"}).status_code == 409        # reste l'ACL
    r = c.delete(u(cid, "/groups/seulmembres"), params={"confirm": "true", "name": "seulmembres"})            # des membres mais aucune ACL
    assert r.status_code == 409 and "1 membre(s), 0 entrée(s)" in r.json()["detail"] and not WRITES
    assert c.delete(u(cid, "/groups/vide"), params={"confirm": "true", "name": "vide"}).status_code == 200 and "vide" not in ST["groups"]
    assert c.delete(u(cid, "/groups/vide"), params={"confirm": "true", "name": "vide"}).status_code == 404


# ---------------------------------------------------------------- Proxmox n'applique pas, erreurs, session
@pytest.mark.parametrize("call", ["create", "update", "delete", "member", "gcreate", "gdelete"])
def test_not_applied_is_reported(api, call):
    c, cid = api
    ST["noapply"] = True
    r = {"create": lambda: create(c, cid),
         "update": lambda: c.put(u(cid, "/users/bob@pve"), json={"enable": False, "confirm": True, "type_name": "bob@pve"}),
         "delete": lambda: c.delete(u(cid, "/users/eve@pve"), params={"confirm": "true", "name": "eve@pve"}),
         "member": lambda: member(c, cid),
         "gcreate": lambda: c.post(u(cid, "/groups"), json={"groupid": "devs", "confirm": True, "type_name": "devs"}),
         "gdelete": lambda: c.delete(u(cid, "/groups/vide"), params={"confirm": "true", "name": "vide"})}[call]()
    assert r.status_code == 502 and "n'a pas" in r.json()["detail"]


def test_proxmox_error_is_translated_without_leak(api):
    c, cid = api
    ST["fail"] = True
    r = create(c, cid, password=USER_PW)
    assert r.status_code == 502 and PERM_SECRET not in r.text and USER_PW not in r.text and UUID not in r.text
    assert PERM_SECRET not in audit_text(c) and USER_PW not in audit_text(c)


def test_everything_requires_an_admin_session(api):
    c, cid = api
    c.delete(f"/api/connections/{cid}/admin-session")
    SEEN.clear()
    calls = [create(c, cid), c.put(u(cid, "/users/bob@pve"), json={"enable": False, "confirm": True, "type_name": "bob@pve"}),
             c.delete(u(cid, "/users/eve@pve"), params={"confirm": "true", "name": "eve@pve"}), member(c, cid), c.get(u(cid, "/users/bob@pve/impact")),
             c.post(u(cid, "/groups"), json={"groupid": "devs", "confirm": True, "type_name": "devs"}),
             c.delete(u(cid, "/groups/vide"), params={"confirm": "true", "name": "vide"})]
    assert [r.status_code for r in calls] == [403] * 7 and not SEEN


def test_requires_login(client):
    assert client.post("/api/connections/1/access/users", json={}).status_code in (401, 403)
    assert client.delete("/api/connections/1/access/groups/x").status_code in (401, 403)


def test_audit_records_actions_without_secrets(api):
    c, cid = api
    create(c, cid, password=USER_PW)
    member(c, cid)
    member(c, cid, group="admins")                                           # refus
    c.delete(u(cid, "/users/eve@pve"), params={"confirm": "true", "name": "eve@pve"})
    pairs = [(a["action"], a["status"]) for a in c.get("/api/audit").json()]
    for a in (("user-create", "started"), ("group-member-add", "started"), ("group-member-add", "error"), ("user-delete", "started")):
        assert a in pairs
    assert USER_PW not in audit_text(c) and UUID not in audit_text(c)
