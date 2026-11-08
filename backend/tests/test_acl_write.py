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
SEEN: list[httpx.Request] = []
WRITES: list[dict] = []
ST: dict = {}
CLOCK = {"t": 1000.0}

ROLES = [
    {"roleid": "Administrator", "special": 1, "privs": "Permissions.Modify,User.Modify,Sys.Audit,VM.Audit"},
    {"roleid": "PVEAuditor", "special": 1, "privs": "Sys.Audit,VM.Audit,Pool.Audit"},
    {"roleid": "PVEVMAdmin", "special": 1, "privs": "VM.PowerMgmt,VM.Config.CPU,VM.Audit"},
    {"roleid": "NoAccess", "special": 1, "privs": ""},
    {"roleid": "Evil", "privs": "User.Modify,VM.Audit"}, {"roleid": "Mod", "privs": "Permissions.Modify"},
    {"roleid": "Grp", "privs": "Group.Allocate"}, {"roleid": "Realm", "privs": "Realm.AllocateUser"}, {"roleid": "RealmA", "privs": "Realm.Allocate"},
]
GROUPS = [{"groupid": "staff", "users": "bob@pve,eve@pve"}, {"groupid": "ops", "users": "kaji@pve"}, {"groupid": "rootg", "users": "root@pam"},
          {"groupid": "adm", "users": "admin@pve"}, {"groupid": "vide"}]
ACL0 = [{"path": "/pool/kaji-test", "type": "user", "ugid": "bob@pve", "roleid": "PVEAuditor", "propagate": 1},
        {"path": "/vms/115", "type": "group", "ugid": "staff", "roleid": "PVEVMAdmin", "propagate": 0},
        {"path": "/pool/kaji-test", "type": "token", "ugid": "bob@pve!ci", "roleid": "PVEAuditor", "propagate": 1},
        {"path": "/pool/kaji-test", "type": "user", "ugid": "bob@pve", "roleid": "Evil", "propagate": 1}]
PUT_OK = {"path", "roles", "users", "groups", "tokens", "propagate", "delete"}


def _handler(request: httpx.Request) -> httpx.Response:
    SEEN.append(request)
    p = request.url.path.removeprefix("/api2/json")
    if request.headers.get("authorization") != ADMIN_AUTH:
        return httpx.Response(401, json={"data": None, "message": PERM_SECRET})
    if ST.get("down"):
        raise httpx.ConnectError("injoignable")
    q = dict(request.url.params)
    if request.method == "GET":
        if p == "/access/permissions":
            return httpx.Response(200, json={"data": ST.get("perms", {q.get("path", "/"): {"VM.Audit": 1, "Sys.Audit": 1}})})
        roles = [dict(r, privs="") if (ST.get("admin_listed_empty") and r["roleid"] == "Administrator") else r for r in ROLES]
        data = {"/access/roles": roles, "/access/groups": GROUPS, "/access/acl": ST["acl"]}.get(p)
        return httpx.Response(200 if data is not None else 501, json={"data": data})
    if (request.method, p) == ("PUT", "/access/acl"):
        from urllib.parse import parse_qs
        body = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        targets = [k for k in ("users", "groups", "tokens") if k in body]
        if set(body) - PUT_OK or len(targets) != 1 or "path" not in body or "roles" not in body or "," in body["roles"] or "," in body[targets[0]]:
            return httpx.Response(400, json={"data": None, "message": f"paramètres refusés {sorted(body)}"})
        if body.get("propagate", "1") not in ("0", "1") or body.get("delete", "0") not in ("0", "1"):
            return httpx.Response(400, json={"data": None, "message": "booléen invalide"})
        if ST.get("fail"):
            return httpx.Response(403, json={"data": None, "message": PERM_SECRET})
        WRITES.append(body)
        if not ST.get("noapply"):
            kind = {"users": "user", "groups": "group", "tokens": "token"}[targets[0]]
            e = {"path": body["path"], "type": kind, "ugid": body[targets[0]], "roleid": body["roles"], "propagate": int(body.get("propagate", 1))}
            if body.get("delete") == "1":
                ST["acl"] = [a for a in ST["acl"] if not (a["path"] == e["path"] and a["ugid"] == e["ugid"] and a["roleid"] == e["roleid"])]
            else:
                ST["acl"].append(e)
        return httpx.Response(200, json={"data": None})
    return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})


@pytest.fixture
def api(client, monkeypatch):
    SEEN.clear(); WRITES.clear(); ST.clear(); ST["acl"] = [dict(a) for a in ACL0]; CLOCK["t"] = 1000.0
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


def url(cid, tail=""):
    return f"/api/connections/{cid}/access/acl{tail}"


def change(**over):
    return {"action": "add", "path": "/pool/kaji-test", "kind": "user", "ugid": "eve@pve", "role": "PVEAuditor", **over}


def apply(c, cid, **over):
    b = change(**over)
    return c.put(url(cid), json={**b, "confirm": True, "type_name": b["ugid"], **{k: v for k, v in over.items() if k in ("confirm", "type_name")}})


def audit_pairs(c):
    return [(a["action"], a["status"]) for a in c.get("/api/audit").json()]


# ---------------------------------------------------------------- application
def test_add_entry_sends_exact_params_with_admin_identity(api):
    c, cid = api
    r = apply(c, cid)
    assert r.status_code == 200 and r.json() == {"applied": True, "action": "add", "path": "/pool/kaji-test", "ugid": "eve@pve", "role": "PVEAuditor"}
    assert WRITES == [{"path": "/pool/kaji-test", "roles": "PVEAuditor", "users": "eve@pve", "propagate": "1"}]
    assert all(r.headers["authorization"] == ADMIN_AUTH for r in SEEN)                      # jamais le token permanent


def test_add_group_and_token_use_their_own_parameter(api):
    c, cid = api
    assert apply(c, cid, kind="group", ugid="staff", path="/vms/116", role="PVEAuditor", propagate=False).status_code == 200
    assert WRITES[-1] == {"path": "/vms/116", "roles": "PVEAuditor", "groups": "staff", "propagate": "0"}
    assert apply(c, cid, kind="token", ugid="bob@pve!deploy", path="/storage/local", role="PVEAuditor").status_code == 200
    assert WRITES[-1] == {"path": "/storage/local", "roles": "PVEAuditor", "tokens": "bob@pve!deploy", "propagate": "1"}


def test_remove_entry(api):
    c, cid = api
    r = apply(c, cid, action="remove", ugid="bob@pve", role="PVEAuditor")
    assert r.status_code == 200 and WRITES == [{"path": "/pool/kaji-test", "roles": "PVEAuditor", "users": "bob@pve", "delete": "1"}]
    assert not any(a["ugid"] == "bob@pve" and a["roleid"] == "PVEAuditor" and a["path"] == "/pool/kaji-test" for a in ST["acl"])


def test_removing_a_dangerous_role_is_allowed(api):
    """Retirer un droit ne l'augmente jamais : on peut nettoyer une entrée « Evil »."""
    c, cid = api
    assert apply(c, cid, action="remove", ugid="bob@pve", role="Evil").status_code == 200


def test_duplicate_and_missing_entries(api):
    c, cid = api
    assert apply(c, cid, ugid="bob@pve").status_code == 409 and not WRITES
    assert apply(c, cid, action="remove", ugid="eve@pve").status_code == 404 and not WRITES


def test_proxmox_not_applying_is_reported_not_hidden(api):
    c, cid = api
    ST["noapply"] = True
    r = apply(c, cid)
    assert r.status_code == 502 and "n'a pas appliqué" in r.json()["detail"]
    assert ("acl-add", "error") in audit_pairs(c)


def test_proxmox_error_is_translated_without_leak(api):
    c, cid = api
    ST["fail"] = True
    r = apply(c, cid)
    assert r.status_code == 502 and PERM_SECRET not in r.text and UUID not in r.text
    assert PERM_SECRET not in c.get("/api/audit").text and UUID not in c.get("/api/audit").text


# ---------------------------------------------------------------- confirmation
def test_confirm_and_retyped_identifier_are_required(api):
    c, cid = api
    b = change()
    assert c.put(url(cid), json=b).status_code == 400
    assert c.put(url(cid), json={**b, "confirm": True}).status_code == 400
    for typed in ("", "EVE@pve", "eve@pve ", "bob@pve", None):
        assert c.put(url(cid), json={**b, "confirm": True, "type_name": typed}).status_code == 400
    assert c.put(url(cid), json={**b, "type_name": "eve@pve"}).status_code == 400
    assert not WRITES and not [r for r in SEEN]                      # refus avant toute lecture ou écriture chez Proxmox


# ---------------------------------------------------------------- chemins
@pytest.mark.parametrize("path", ["/", "/access", "/access/roles", "/access/groups", "/vms", "/pool", "/storage", "/nodes", "/sdn", "/sdn/zones/x",
                                  "/pool/", "/pool/a b", "/pool/../", "/pool/a/b", "/vms/12", "/vms/abc", "/vms/115/", "/pool/kaji-test\n", "pool/x", "",
                                  "/pool/" + "x" * 41, "/nodes/a_b", "/POOL/x"])
def test_forbidden_paths_never_reach_proxmox(api, path):
    c, cid = api
    assert apply(c, cid, path=path).status_code == 422 and not WRITES and not SEEN


@pytest.mark.parametrize("path", ["/pool/kaji-test", "/vms/115", "/storage/local-lvm", "/nodes/enzo2", "/pool/a-b_c"])
def test_allowed_paths(api, path):
    c, cid = api
    assert apply(c, cid, path=path).status_code == 200


# ---------------------------------------------------------------- rôles
@pytest.mark.parametrize("role", ["Administrator", "Evil", "Mod", "Grp", "Realm", "RealmA"])
def test_dangerous_roles_are_refused_even_when_confirmed(api, role):
    c, cid = api
    r = apply(c, cid, role=role)
    assert r.status_code == 403 and "permettrait de modifier les droits" in r.json()["detail"] and not WRITES


def test_administrator_is_refused_by_name_even_if_listed_without_privileges(api):
    """Défense en profondeur : le nom suffit, sans dépendre de la liste des privilèges renvoyée par Proxmox."""
    c, cid = api
    ST["admin_listed_empty"] = True
    r = apply(c, cid, role="Administrator")
    assert r.status_code == 403 and not WRITES
    assert c.post(url(cid, "/preview"), json=change(role="Administrator")).json()["allowed"] is False


def test_unknown_role_refused(api):
    c, cid = api
    assert apply(c, cid, role="Inconnu").status_code == 403 and not WRITES


@pytest.mark.parametrize("role", ["", "a b", "A;B", "x" * 70, "../x"])
def test_role_format_validated(api, role):
    c, cid = api
    assert apply(c, cid, role=role).status_code == 422 and not WRITES


def test_noaccess_is_allowed(api):
    c, cid = api
    assert apply(c, cid, role="NoAccess").status_code == 200


# ---------------------------------------------------------------- identités protégées
@pytest.mark.parametrize("kind,ugid", [("user", "root@pam"), ("user", "kaji@pve"), ("user", "admin@pve"), ("token", "kaji@pve!kaji"), ("token", "kaji@pve!autre"),
                                       ("token", "admin@pve!kaji-admin"), ("token", "admin@pve!autre"), ("token", "root@pam!x1"),
                                       ("group", "ops"), ("group", "rootg"), ("group", "adm")])
@pytest.mark.parametrize("action", ["add", "remove"])
def test_protected_identities_are_untouchable(api, kind, ugid, action):
    c, cid = api
    r = apply(c, cid, kind=kind, ugid=ugid, action=action)
    assert r.status_code == 403 and "protég" in r.json()["detail"] and not WRITES


def test_group_without_protected_member_is_fine(api):
    c, cid = api
    assert apply(c, cid, kind="group", ugid="vide", path="/pool/kaji-test").status_code == 200


@pytest.mark.parametrize("kind,ugid", [("user", "nom"), ("user", "a b@pve"), ("user", "a@"), ("user", "a;b@pve"), ("user", "bob@pve,eve@pve"), ("token", "bob@pve"),
                                       ("token", "bob@pve!"), ("token", "bob@pve!1x"), ("token", "bob@pve!a,b"), ("group", "a b"), ("group", "a,b"), ("group", ""),
                                       ("autre", "bob@pve")])
def test_target_format_validated_and_never_a_list(api, kind, ugid):
    c, cid = api
    r = apply(c, cid, kind=kind, ugid=ugid)
    assert r.status_code == 422 and not WRITES and not SEEN


def test_action_must_be_known(api):
    c, cid = api
    assert apply(c, cid, action="replace").status_code == 422 and apply(c, cid, action="removeall").status_code == 422 and not WRITES


# ---------------------------------------------------------------- aperçu
def test_preview_describes_without_writing(api):
    c, cid = api
    r = c.post(url(cid, "/preview"), json=change(ugid="bob@pve", role="PVEVMAdmin"))
    j = r.json()
    assert r.status_code == 200 and j["allowed"] is True and j["entry_exists"] is False and j["would_change"] is True
    assert j["role_privs"] == ["VM.Audit", "VM.Config.CPU", "VM.PowerMgmt"] and j["effective_before"] == ["Sys.Audit", "VM.Audit"]
    assert j["estimate_after"] == ["Sys.Audit", "VM.Audit", "VM.Config.CPU", "VM.PowerMgmt"]
    assert {a["roleid"] for a in j["existing_entries"]} == {"PVEAuditor", "Evil"} and not WRITES
    assert any(q.url.path.endswith("/access/permissions") and q.url.params.get("userid") == "bob@pve" for q in SEEN)


def test_preview_reports_refusals_without_calling_for_permissions(api):
    c, cid = api
    j = c.post(url(cid, "/preview"), json=change(role="Administrator")).json()
    assert j["allowed"] is False and "permettrait" in j["reason"] and j["would_change"] is False and j["effective_before"] is None
    j = c.post(url(cid, "/preview"), json=change(kind="user", ugid="root@pam")).json()
    assert j["allowed"] is False and "protégée" in j["reason"]
    assert not any(q.url.path.endswith("/access/permissions") for q in SEEN) and not WRITES


def test_preview_of_a_removal(api):
    c, cid = api
    j = c.post(url(cid, "/preview"), json=change(action="remove", ugid="bob@pve", role="PVEAuditor")).json()
    assert j["entry_exists"] is True and j["would_change"] is True and j["estimate_after"] is None


def test_preview_validates_like_apply(api):
    c, cid = api
    assert c.post(url(cid, "/preview"), json=change(path="/")).status_code == 422 and not SEEN


# ---------------------------------------------------------------- session administrateur
def test_everything_requires_an_admin_session(api):
    c, cid = api
    c.delete(f"/api/connections/{cid}/admin-session")
    SEEN.clear()
    assert apply(c, cid).status_code == 403 and c.post(url(cid, "/preview"), json=change()).status_code == 403 and not SEEN


def test_expired_session_stops_writes(api):
    c, cid = api
    CLOCK["t"] += 1801
    assert apply(c, cid).status_code == 403 and not WRITES


def test_logout_stops_writes(api):
    c, cid = api
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"username": "admin", "password": PWD})
    assert apply(c, cid).status_code == 403 and not WRITES


def test_requires_login(client):
    assert client.put("/api/connections/1/access/acl", json=change()).status_code in (401, 403)
    assert client.post("/api/connections/1/access/acl/preview", json=change()).status_code in (401, 403)


# ---------------------------------------------------------------- audit
def test_audit_records_success_refusal_and_error_without_secret(api):
    c, cid = api
    apply(c, cid)                                     # succès
    apply(c, cid, role="Administrator")               # refus
    apply(c, cid, ugid="bob@pve")                     # doublon
    apply(c, cid, action="remove", ugid="bob@pve", role="PVEAuditor")
    pairs = audit_pairs(c)
    for a in (("acl-add", "started"), ("acl-add", "error"), ("acl-remove", "started")):
        assert a in pairs
    text = c.get("/api/audit").text
    assert UUID not in text and PERM_SECRET not in text and "PVEAuditor pour eve@pve sur /pool/kaji-test" in text
