import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import roles as R
from app.db import get_engine
from app.main import app

PWD = "un-mot-de-passe-solide"
G = "/api/connections/1/guests/enzo"


# ------------------------------------------------------------------ politique (fonction pure)
@pytest.mark.parametrize("method,path", [
    ("POST", f"{G}/qemu/115/start"), ("POST", f"{G}/lxc/116/shutdown"), ("POST", f"{G}/qemu/115/stop"), ("POST", f"{G}/lxc/9/reboot"),
    ("POST", f"{G}/qemu/115/reset"), ("POST", f"{G}/qemu/115/suspend"), ("POST", f"{G}/qemu/115/resume"), ("POST", f"{G}/qemu/115/hibernate"),
    ("POST", f"{G}/qemu/115/snapshots"), ("POST", f"{G}/lxc/116/snapshots"),
])
def test_operator_may_run_power_actions_and_create_snapshots(method, path):
    assert R.allowed("operator", method, path) and R.allowed("admin", method, path) and not R.allowed("viewer", method, path)


@pytest.mark.parametrize("method,path", [
    ("POST", f"{G}/qemu/115/console"), ("POST", f"{G}/qemu/115/spice"), ("POST", f"{G}/qemu/115/migrate"), ("POST", f"{G}/qemu/115/clone"), ("POST", f"{G}/qemu/115/template"),
    ("POST", f"{G}/qemu/115/snapshots/s1/rollback"), ("POST", f"{G}/qemu/115/disks"), ("POST", f"{G}/qemu/115/remote-migrate"), ("DELETE", f"{G}/qemu/115"),
    ("DELETE", f"{G}/qemu/115/snapshots/s1"), ("PUT", f"{G}/qemu/115/options"), ("PATCH", f"{G}/qemu/115/disks/scsi0/options"), ("POST", f"{G}/lxc/116/reset"),
    ("DELETE", f"{G}/qemu/115/start"), ("PUT", f"{G}/qemu/115/snapshots"), ("PATCH", f"{G}/lxc/116/reboot"), ("DELETE", f"{G}/qemu/115/snapshots"),
    ("POST", f"{G}/qemu/115/start/extra"), ("POST", f"{G}/qemu/115/start/"), ("POST", f"{G}/qemu/abc/start"), ("POST", f"{G}/../x/qemu/1/start"),
    ("POST", "/api/connections/1/access/acl"), ("POST", "/api/connections/1/admin-session"), ("PUT", "/api/connections/1/datacenter/options"),
    ("POST", "/api/connections/1/nodes/enzo/services/pveproxy/restart"), ("DELETE", "/api/connections/1"), ("POST", "/api/connections"),
])
def test_operator_may_not_do_anything_else(method, path):
    assert not R.allowed("operator", method, path) and R.allowed("admin", method, path)


@pytest.mark.parametrize("path", ["/api/connections/1/guests", "/api/audit", "/api/connections/1/cluster/log", "/api/connections/1/access/users"])
def test_everybody_may_read(path):
    for role in R.ROLES:
        assert R.allowed(role, "GET", path)


@pytest.mark.parametrize("role", ["viewer", "operator", "inconnu", "", None, "ADMIN", "Admin"])
def test_only_admins_reach_user_management(role):
    for m in ("GET", "POST", "PUT", "DELETE"):
        assert not R.allowed(role, m, "/api/kaji-users") and not R.allowed(role, m, "/api/kaji-users/3")
    assert R.allowed("admin", "GET", "/api/kaji-users") and R.allowed("admin", "DELETE", "/api/kaji-users/3")
    assert R.allowed("admin", "GET", "/api/kaji-users-extra") is True            # un autre préfixe n'est pas la gestion des utilisateurs


def test_unknown_roles_are_viewers_and_self_service_is_open():
    assert R.normalize("root") == "viewer" and R.normalize(None) == "viewer" and R.normalize("operator") == "operator"
    for role in R.ROLES:
        assert R.allowed(role, "POST", "/api/auth/logout") and R.allowed(role, "POST", "/api/auth/password")
    assert not R.allowed("root", "POST", f"{G}/qemu/1/start")


def test_websockets_are_admin_only():
    assert R.allowed("admin", "GET", "/api/x/ws", websocket=True)
    assert not R.allowed("operator", "GET", "/api/x/ws", websocket=True) and not R.allowed("viewer", "GET", "/api/x/ws", websocket=True)


# ------------------------------------------------------------------ gestion des utilisateurs (API)
def _login(name, pwd=PWD):
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": name, "password": pwd})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
def admin(client):
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    return client


def _create(c, name, role, pwd=PWD):
    return c.post("/api/kaji-users", json={"username": name, "password": pwd, "role": role})


def test_admin_creates_users_with_roles(admin):
    r = _create(admin, "alice", "viewer")
    assert r.status_code == 201 and r.json()["role"] == "viewer" and "password" not in r.text and "hash" not in r.text
    _create(admin, "olivier", "operator")
    users = {u["username"]: u["role"] for u in admin.get("/api/kaji-users").json()}
    assert users == {"admin": "admin", "alice": "viewer", "olivier": "operator"}
    assert _login("alice").get("/api/auth/me").json() == {"username": "alice", "role": "viewer"}


@pytest.mark.parametrize("body", [
    {"username": "ab", "password": PWD, "role": "viewer"}, {"username": "a b c", "password": PWD, "role": "viewer"}, {"username": "-abc", "password": PWD, "role": "viewer"},
    {"username": "abc\n", "password": PWD, "role": "viewer"}, {"username": "abc", "password": "court", "role": "viewer"}, {"username": "abc", "password": PWD, "role": "root"},
    {"username": "abc", "password": PWD, "role": "ADMIN"}, {"username": "abc", "password": PWD}, {"username": "abc", "password": PWD, "role": "admin\n"},
])
def test_invalid_creations_are_refused(admin, body):
    r = admin.post("/api/kaji-users", json=body)
    assert r.status_code == 422 and PWD not in r.text
    assert [u["username"] for u in admin.get("/api/kaji-users").json()] == ["admin"]


def test_duplicate_names_are_refused_case_insensitively(admin):
    assert _create(admin, "alice", "viewer").status_code == 201
    assert _create(admin, "Alice", "admin").status_code == 409 and _create(admin, "alice", "admin").status_code == 409


def test_viewer_cannot_write_nor_manage_users(admin):
    _create(admin, "alice", "viewer")
    v = _login("alice")
    assert v.get("/api/kaji-users").status_code == 403 and _create(v, "mallory", "admin").status_code == 403
    assert v.put("/api/kaji-users/1", json={"role": "viewer"}).status_code == 403 and v.delete("/api/kaji-users/1?confirm=true&name=admin").status_code == 403
    assert v.post("/api/connections/1/guests/enzo/qemu/115/start").status_code == 403
    assert v.post("/api/connections", json={"name": "x"}).status_code == 403
    assert v.get("/api/connections").status_code == 200                               # la lecture reste permise
    assert [u["username"] for u in admin.get("/api/kaji-users").json()] == ["admin", "alice"]
    assert ("role-refused", "error") in {(a["action"], a["status"]) for a in admin.get("/api/audit").json()}


def test_operator_reaches_power_routes_but_not_the_rest(admin):
    _create(admin, "olivier", "operator")
    o = _login("olivier")
    assert o.post("/api/connections/1/guests/enzo/qemu/115/start").status_code != 403           # autorisé : la route répond (404, connexion inconnue)
    assert o.post("/api/connections/1/guests/enzo/qemu/115/migrate", json={}).status_code == 403
    assert o.post("/api/connections/1/guests/enzo/qemu/115/console", json={}).status_code == 403
    assert o.post("/api/connections/1/admin-session", json={}).status_code == 403
    assert o.get("/api/kaji-users").status_code == 403


def test_users_keep_self_service(admin):
    _create(admin, "alice", "viewer")
    v = _login("alice")
    assert v.post("/api/auth/password", json={"current_password": PWD, "new_password": "un-autre-mot-de-passe"}).status_code == 200
    assert v.post("/api/auth/logout").status_code == 204


def test_role_change_applies_immediately(admin):
    uid = _create(admin, "alice", "viewer").json()["id"]
    v = _login("alice")
    assert v.post("/api/connections/1/guests/enzo/qemu/115/start").status_code == 403
    assert admin.put(f"/api/kaji-users/{uid}", json={"role": "operator"}).status_code == 200
    assert v.post("/api/connections/1/guests/enzo/qemu/115/start").status_code != 403
    assert admin.put(f"/api/kaji-users/{uid}", json={"role": "viewer"}).status_code == 200
    assert v.post("/api/connections/1/guests/enzo/qemu/115/start").status_code == 403


def test_cannot_change_own_role_or_demote_the_last_admin(admin):
    me = admin.get("/api/kaji-users").json()[0]["id"]
    assert admin.put(f"/api/kaji-users/{me}", json={"role": "viewer"}).status_code == 409
    other = _create(admin, "bob", "admin").json()["id"]
    assert admin.put(f"/api/kaji-users/{other}", json={"role": "viewer"}).status_code == 200           # un autre administrateur reste
    admin.put(f"/api/kaji-users/{other}", json={"role": "admin"})
    b = _login("bob")
    assert b.put(f"/api/kaji-users/{me}", json={"role": "viewer"}).status_code == 200
    assert admin.get("/api/auth/me").json()["role"] == "viewer"
    assert b.put(f"/api/kaji-users/{other}", json={"role": "operator"}).status_code == 409             # soi-même
    assert b.put(f"/api/kaji-users/{me}", json={"role": "admin"}).status_code == 200


def test_last_admin_cannot_be_demoted_by_someone_else(admin):
    me = admin.get("/api/kaji-users").json()[0]["id"]
    uid = _create(admin, "bob", "admin").json()["id"]
    b = _login("bob")
    admin.put(f"/api/kaji-users/{uid}", json={"role": "viewer"})
    # bob est devenu viewer : seul « admin » reste ; un administrateur ne peut pas se dégrader lui-même, et personne d'autre n'est admin
    assert b.put(f"/api/kaji-users/{me}", json={"role": "viewer"}).status_code == 403
    assert admin.put(f"/api/kaji-users/{me}", json={"role": "viewer"}).status_code == 409


def test_delete_needs_confirmation_and_refuses_self_and_last_admin(admin):
    me = admin.get("/api/kaji-users").json()[0]["id"]
    uid = _create(admin, "alice", "viewer").json()["id"]
    assert admin.delete(f"/api/kaji-users/{uid}").status_code == 400
    assert admin.delete(f"/api/kaji-users/{uid}?confirm=true&name=autre").status_code == 400
    assert admin.delete(f"/api/kaji-users/{me}?confirm=true&name=admin").status_code == 409
    assert admin.delete("/api/kaji-users/9999?confirm=true&name=x").status_code == 404
    assert admin.delete(f"/api/kaji-users/{uid}?confirm=true&name=alice").json() == {"deleted": "alice"}
    assert [u["username"] for u in admin.get("/api/kaji-users").json()] == ["admin"]


def test_self_guards_hold_even_when_another_admin_exists(admin):
    """Avec deux administrateurs, ni se supprimer ni se dégrader soi-même : ces gardes ne dépendent pas de la règle « au moins un administrateur »."""
    me = admin.get("/api/kaji-users").json()[0]["id"]
    assert _create(admin, "bob", "admin").status_code == 201
    assert admin.delete(f"/api/kaji-users/{me}?confirm=true&name=admin").status_code == 409
    assert admin.put(f"/api/kaji-users/{me}", json={"role": "operator"}).status_code == 409
    assert admin.put(f"/api/kaji-users/{me}", json={"role": "admin"}).status_code == 200            # inchangé : pas un changement
    assert admin.get("/api/auth/me").json()["role"] == "admin"


def test_deleting_a_user_revokes_their_sessions(admin):
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from app.models import UserSession
    uid = _create(admin, "alice", "viewer").json()["id"]
    v = _login("alice")
    assert v.get("/api/auth/me").status_code == 200
    with Session(get_engine()) as db:
        assert db.scalar(select(func.count()).select_from(UserSession).where(UserSession.user_id == uid)) == 1
    assert admin.delete(f"/api/kaji-users/{uid}?confirm=true&name=alice").status_code == 200
    assert v.get("/api/auth/me").status_code == 401
    with Session(get_engine()) as db:                                                               # pas de session orpheline en base
        assert db.scalar(select(func.count()).select_from(UserSession).where(UserSession.user_id == uid)) == 0


def test_password_reset_revokes_sessions_and_never_echoes(admin):
    uid = _create(admin, "alice", "viewer").json()["id"]
    v = _login("alice")
    r = admin.put(f"/api/kaji-users/{uid}", json={"password": "nouveau-mot-de-passe-1"})
    assert r.status_code == 200 and "nouveau-mot-de-passe-1" not in r.text and "nouveau-mot-de-passe-1" not in admin.get("/api/audit").text
    assert v.get("/api/auth/me").status_code == 401
    assert _login("alice", "nouveau-mot-de-passe-1").get("/api/auth/me").status_code == 200
    assert admin.put(f"/api/kaji-users/{uid}", json={}).status_code == 422
    assert admin.put(f"/api/kaji-users/{uid}", json={"password": "court"}).status_code == 422


def test_audit_never_holds_passwords(admin):
    _create(admin, "alice", "operator", pwd="mot-de-passe-secret-42")
    t = admin.get("/api/audit").text
    assert "kaji-user-create" in t and "alice" in t and "mot-de-passe-secret-42" not in t


def test_unauthenticated_access_is_401(client):
    assert client.get("/api/kaji-users").status_code == 401 and client.post("/api/kaji-users", json={}).status_code == 401


def test_migration_3_gives_existing_accounts_the_admin_role(tmp_path):
    """Une base déployée AVANT les rôles (version 2) : la colonne est ajoutée, les comptes existants restent administrateurs, sauvegarde faite."""
    from sqlalchemy import create_engine, inspect

    from app import models  # noqa: F401
    from app.db import Base
    from app.migrations import run_migrations
    e = create_engine(f"sqlite:///{tmp_path / 'kaji.db'}")
    Base.metadata.create_all(e)
    with e.begin() as c:
        c.execute(text("ALTER TABLE admin_users DROP COLUMN role"))
        c.execute(text("INSERT INTO admin_users (username, password_hash, created_at) VALUES ('enzo', 'h', '2026-01-01')"))
        c.execute(text("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"))
        c.execute(text("INSERT INTO schema_migrations VALUES (1, 'a', '2026-01-01'), (2, 'b', '2026-01-02')"))
    assert "role" not in {col["name"] for col in inspect(e).get_columns("admin_users")}
    r = run_migrations(e)
    assert r["applied"] == [3] and r["backup"] is not None
    with e.connect() as c:
        assert c.execute(text("SELECT username, role FROM admin_users")).one() == ("enzo", "admin")
    assert run_migrations(e)["applied"] == []                                                      # rejouable sans effet


def test_corrupted_role_is_read_only(admin):
    uid = _create(admin, "alice", "operator").json()["id"]
    v = _login("alice")
    with get_engine().begin() as conn:
        conn.execute(text("UPDATE admin_users SET role = 'dieu' WHERE id = :i"), {"i": uid})
    assert v.post("/api/connections/1/guests/enzo/qemu/115/start").status_code == 403 and v.get("/api/auth/me").json()["role"] == "viewer"
