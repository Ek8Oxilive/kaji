import httpx
import pytest

from app import adminsession as A
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
PERM_SECRET = "s3cr3t-value-xyz"                                  # token permanent de Kaji (connexion)
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": PERM_SECRET}
ADMIN_UUID = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
ADMIN = {"user": "admin@pve", "token_id": "kaji-admin", "secret": ADMIN_UUID}
ADMIN_AUTH = f"PVEAPIToken=admin@pve!kaji-admin={ADMIN_UUID}"
PERM_AUTH = f"PVEAPIToken=kaji@pve!kaji={PERM_SECRET}"
PERMS = {"/": {"Sys.Audit": 1}, "/pool/kaji-test": {"Permissions.Modify": 1, "VM.Audit": 1}, "/vms": {"Permissions.Modify": 0}}
SEEN: list[httpx.Request] = []
ST: dict = {}
CLOCK = {"t": 1000.0}


def _handler(request: httpx.Request) -> httpx.Response:
    SEEN.append(request)
    if ST.get("down"):
        raise httpx.ConnectError("injoignable")
    p = request.url.path.removeprefix("/api2/json")
    if p != "/access/permissions" or request.method != "GET":
        return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})
    auth = request.headers.get("authorization")
    if auth == PERM_AUTH and ST.get("perm_ok"):                  # le token permanent n'est accepté que s'il a reçu les droits (option du propriétaire)
        return httpx.Response(200, json={"data": ST.get("perms", PERMS)})
    if auth != ADMIN_AUTH:                                       # le token permanent, ou un faux : refusé
        return httpx.Response(401, json={"data": None, "message": PERM_SECRET})
    return httpx.Response(200, json={"data": ST.get("perms", PERMS)})


@pytest.fixture
def api(client, monkeypatch):
    SEEN.clear(); ST.clear(); CLOCK["t"] = 1000.0
    A.sessions.clear()
    monkeypatch.setattr(A, "_now", lambda: CLOCK["t"])
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    A.sessions.clear()
    app.dependency_overrides.clear()


def u(cid, tail=""):
    return f"/api/connections/{cid}/admin-session{tail}"


def calls():
    return [r for r in SEEN]


def audit_text(c):
    return c.get("/api/audit").text


def open_ok(c, cid, **over):
    return c.post(u(cid), json={**ADMIN, **over})


# ---------------------------------------------------------------- ouverture
def test_open_validates_token_with_proxmox_and_reports_rights(api):
    c, cid = api
    r = open_ok(c, cid)
    assert r.status_code == 201
    j = r.json()
    assert j["active"] is True and j["user"] == "admin@pve" and j["token_id"] == "kaji-admin" and j["seconds_left"] == 1800 and j["renewals"] == 0
    assert j["can_modify_permissions"] is True and j["modify_paths"] == ["/pool/kaji-test"]     # « /vms » : droit à 0, pas compté
    assert len(calls()) == 1 and calls()[0].headers["authorization"] == ADMIN_AUTH               # vérifié avec le token collé, jamais avec le permanent


def test_secret_never_leaves(api):
    c, cid = api
    r = open_ok(c, cid)
    texts = [r.text, c.get(u(cid)).text, c.get(u(cid, "/whoami")).text, audit_text(c), str(r.headers)]
    for t in texts:
        assert ADMIN_UUID not in t
    assert ADMIN_UUID not in repr(A.sessions.get(c.get("/api/auth/me") and next(iter(A.sessions._items)), cid))


def test_status_without_session(api):
    c, cid = api
    assert c.get(u(cid)).json() == {"active": False}


def test_token_that_equals_the_permanent_one_is_refused(api):
    c, cid = api
    r = c.post(u(cid), json={"user": "kaji@pve", "token_id": "kaji", "secret": ADMIN_UUID})
    assert r.status_code == 422 and "distinct" in r.json()["detail"] and not calls()
    assert c.get(u(cid)).json() == {"active": False}


@pytest.mark.parametrize("over", [
    {"user": "admin"}, {"user": "admin@"}, {"user": "@pve"}, {"user": "a b@pve"}, {"user": "a;b@pve"}, {"user": "admin@pve\n"}, {"user": "x" * 70 + "@pve"},
    {"token_id": "1abc"}, {"token_id": "a"}, {"token_id": "a b"}, {"token_id": "a!b"}, {"token_id": "x" * 70},
    {"secret": "pas-un-uuid"}, {"secret": ADMIN_UUID + "x"}, {"secret": "x" + ADMIN_UUID}, {"secret": ""}, {"secret": ADMIN_UUID.replace("-", "")},
    {"secret": ADMIN_UUID[:-1] + "g"},
])
def test_formats_validated_without_call_and_without_echo(api, over):
    c, cid = api
    r = open_ok(c, cid, **over)
    assert r.status_code == 422 and not calls()
    for v in over.values():
        assert not v or len(str(v)) < 4 or str(v) not in r.text          # la valeur saisie n'est jamais renvoyée


def test_proxmox_refusing_the_token_opens_nothing(api):
    c, cid = api
    r = open_ok(c, cid, secret="11111111-2222-4333-8444-555555555555")
    assert r.status_code == 502 and PERM_SECRET not in r.text and "11111111" not in r.text
    assert c.get(u(cid)).json() == {"active": False}
    assert ("error" in audit_text(c)) and "11111111-2222" not in audit_text(c)


def test_proxmox_down_opens_nothing(api):
    c, cid = api
    ST["down"] = True
    assert open_ok(c, cid).status_code in (502, 504) and c.get(u(cid)).json() == {"active": False}


def test_reopening_replaces_the_session(api):
    c, cid = api
    open_ok(c, cid)
    CLOCK["t"] += 600
    assert open_ok(c, cid).json()["seconds_left"] == 1800 and c.get(u(cid)).json()["seconds_left"] == 1800


def test_unknown_connection_404(api):
    c, _ = api
    assert open_ok(c, 9999).status_code == 404 and not calls()


# ---------------------------------------------------------------- expiration et renouvellement
def test_session_expires_by_itself(api):
    c, cid = api
    open_ok(c, cid)
    CLOCK["t"] += 1799
    assert c.get(u(cid)).json()["active"] is True and c.get(u(cid)).json()["seconds_left"] == 1
    CLOCK["t"] += 2
    assert c.get(u(cid)).json() == {"active": False}
    assert c.get(u(cid, "/whoami")).status_code == 403


def test_renew_extends_but_never_beyond_four_hours(api):
    c, cid = api
    open_ok(c, cid)
    CLOCK["t"] += 1000
    r = c.post(u(cid, "/renew"))
    assert r.status_code == 200 and r.json()["seconds_left"] == 1800 and r.json()["renewals"] == 1
    opened = CLOCK["t"] - 1000
    for _ in range(20):
        CLOCK["t"] += max(1, min(1700, c.get(u(cid)).json()["seconds_left"] - 1))          # on renouvelle toujours avant l'expiration
        r = c.post(u(cid, "/renew"))
        if r.status_code == 409:
            break
        assert r.status_code == 200 and (CLOCK["t"] + r.json()["seconds_left"]) - opened <= 4 * 3600 + 1
    assert r.status_code == 409 and "maximal" in r.json()["detail"]
    CLOCK["t"] += 14400
    assert c.get(u(cid)).json() == {"active": False}


def test_renew_without_session_404(api):
    c, cid = api
    assert c.post(u(cid, "/renew")).status_code == 404
    open_ok(c, cid)
    CLOCK["t"] += 1801
    assert c.post(u(cid, "/renew")).status_code == 404            # expirée : on ne la ressuscite pas


# ---------------------------------------------------------------- fermeture et liaison à la session de connexion
def test_close_is_idempotent_and_final(api):
    c, cid = api
    open_ok(c, cid)
    assert c.delete(u(cid)).status_code == 204 and c.get(u(cid)).json() == {"active": False}
    assert c.get(u(cid, "/whoami")).status_code == 403 and c.delete(u(cid)).status_code == 204


def test_logout_closes_the_admin_session(api):
    c, cid = api
    open_ok(c, cid)
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"username": "admin", "password": PWD})
    assert c.get(u(cid)).json() == {"active": False} and c.get(u(cid, "/whoami")).status_code == 403
    assert not A.sessions._items


def test_logout_all_closes_the_admin_session(api):
    c, cid = api
    open_ok(c, cid)
    c.post("/api/auth/logout-all")
    c.post("/api/auth/login", json={"username": "admin", "password": PWD})
    assert not A.sessions._items and c.get(u(cid)).json() == {"active": False}


def test_password_change_closes_the_admin_session(api):
    c, cid = api
    open_ok(c, cid)
    assert c.post("/api/auth/password", json={"current_password": PWD, "new_password": "un-autre-mot-de-passe-solide"}).status_code == 200
    assert not A.sessions._items and c.get(u(cid)).json() == {"active": False}


def test_a_new_login_does_not_inherit_the_session(api):
    """La session administrateur est liée à la session de connexion (jti), pas seulement à l'utilisateur."""
    c, cid = api
    open_ok(c, cid)
    other_session = c.post("/api/auth/login", json={"username": "admin", "password": PWD})        # nouvelle session, même utilisateur
    assert other_session.status_code == 200 and c.get(u(cid)).json() == {"active": False}


def test_session_is_bound_to_its_connection(api):
    c, cid = api
    other = c.post("/api/connections", json={**BODY, "name": "autre", "host": "10.0.0.6"}).json()["id"]
    open_ok(c, cid)
    assert c.get(u(other)).json() == {"active": False} and c.get(u(other, "/whoami")).status_code == 403
    assert c.post(u(other, "/renew")).status_code == 404


# ---------------------------------------------------------------- whoami (lecture seule, avec l'identité du token collé)
def test_whoami_uses_the_admin_identity(api):
    c, cid = api
    open_ok(c, cid)
    SEEN.clear()
    r = c.get(u(cid, "/whoami"))
    assert r.status_code == 200 and r.json()["can_modify_permissions"] is True and r.json()["modify_paths"] == ["/pool/kaji-test"]
    assert len(calls()) == 1 and calls()[0].headers["authorization"] == ADMIN_AUTH


def test_whoami_requires_an_admin_session(api):
    c, cid = api
    r = c.get(u(cid, "/whoami"))
    assert r.status_code == 403 and "Session administrateur requise" in r.json()["detail"] and not calls()


def test_whoami_translates_proxmox_errors_without_leak(api):
    c, cid = api
    open_ok(c, cid)
    ST["down"] = True
    r = c.get(u(cid, "/whoami"))
    assert r.status_code in (502, 504) and ADMIN_UUID not in r.text


# ---------------------------------------------------------------- limite d'essais
def test_attempts_are_limited_then_released(api):
    c, cid = api
    for _ in range(5):
        assert open_ok(c, cid, secret="11111111-2222-4333-8444-555555555555").status_code == 502
    assert open_ok(c, cid).status_code == 429                                 # même avec le bon token
    assert c.get(u(cid)).json() == {"active": False}
    CLOCK["t"] += 61
    assert open_ok(c, cid).status_code == 201


# ---------------------------------------------------------------- audit
def test_audit_records_actions_without_secret(api):
    c, cid = api
    open_ok(c, cid)
    c.post(u(cid, "/renew"))
    c.delete(u(cid))
    c.post(u(cid), json={"user": "kaji@pve", "token_id": "kaji", "secret": ADMIN_UUID})          # refus
    acts = [(a["action"], a["status"]) for a in c.get("/api/audit").json()]
    for a in (("admin-session-open", "started"), ("admin-session-renew", "started"), ("admin-session-close", "started"), ("admin-session-open", "error")):
        assert a in acts
    assert ADMIN_UUID not in audit_text(c)


def test_requires_login(client):
    for method, tail in (("get", ""), ("post", ""), ("post", "/renew"), ("delete", ""), ("get", "/whoami")):
        r = getattr(client, method)(u(1, tail))
        assert r.status_code in (401, 403, 422), (method, tail, r.status_code)
        assert r.status_code != 200


# ---------------------------------------------------------------- unités
def test_repr_never_shows_the_secret():
    from pydantic import SecretStr
    s = A.AdminSession(conn_id=1, owner_id=1, user="a@pve", token_id="t1", secret=SecretStr(ADMIN_UUID), opened_at=0, expires_at=0)
    assert ADMIN_UUID not in repr(s) and ADMIN_UUID not in str(s) and ADMIN_UUID not in f"{s}"


def test_shape_permissions_is_defensive():
    from app.routers.admin_session import shape_permissions
    assert shape_permissions(None) == {"can_modify_permissions": False, "modify_paths": [], "paths": 0}
    assert shape_permissions({"/": "x", 5: {"Permissions.Modify": 1}, "/a": {"Permissions.Modify": "1"}, "/b": {"Permissions.Modify": True}})["modify_paths"] == ["/b"]
    many = {f"/p{i}": {"Permissions.Modify": 1} for i in range(80)}
    assert len(shape_permissions(many)["modify_paths"]) == 50
    assert shape_permissions({"/" + "x" * 300: {"Permissions.Modify": 1}})["modify_paths"] == []


def test_store_renew_checks_the_connection_itself():
    """Défense en profondeur : même sans le contrôle de la route, le magasin ne prolonge pas la session d'une autre connexion."""
    from pydantic import SecretStr
    st = A.AdminSessions()
    st.open("jti-1", 1, 7, "a@pve", "t1", SecretStr(ADMIN_UUID))
    assert st.renew("jti-1", 8) is None and st.renew("jti-1", 7) is not None and st.get("jti-1", 8) is None
    assert st.close_owner(1) == 1 and st.get("jti-1") is None


# ------------------------------------------- option : ouvrir avec le token permanent de Kaji (KAJI_ADMIN_USE_KAJI_TOKEN)
@pytest.fixture
def kaji_token_on(monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "kaji_admin_use_kaji_token", True)


def test_kaji_token_option_is_off_by_default(api):
    c, cid = api
    assert c.get(u(cid, "/kaji-token")).json() == {"allowed": False}
    ST["perm_ok"] = True
    r = c.post(u(cid, "/kaji-token"))
    assert r.status_code == 403 and "KAJI_ADMIN_USE_KAJI_TOKEN" in r.json()["detail"] and not calls()
    assert c.get(u(cid)).json() == {"active": False}


def test_kaji_token_option_opens_a_session_with_the_permanent_token(api, kaji_token_on):
    c, cid = api
    ST["perm_ok"] = True
    assert c.get(u(cid, "/kaji-token")).json() == {"allowed": True}
    r = c.post(u(cid, "/kaji-token"))
    assert r.status_code == 201
    j = r.json()
    assert j["active"] is True and j["user"] == "kaji@pve" and j["token_id"] == "kaji" and j["seconds_left"] == 1800
    assert len(calls()) == 1 and calls()[0].headers["authorization"] == PERM_AUTH
    assert c.get(u(cid, "/whoami")).status_code == 200                    # la session sert aux routes d'écriture comme une autre
    for t in (r.text, c.get(u(cid)).text, audit_text(c)):
        assert PERM_SECRET not in t
    assert "token permanent de Kaji" in audit_text(c)


def test_kaji_token_option_without_rights_opens_nothing(api, kaji_token_on):
    c, cid = api                                                          # Proxmox refuse le token (401) : rien n'est ouvert, pas de fuite
    r = c.post(u(cid, "/kaji-token"))
    assert r.status_code in (401, 403, 502) and PERM_SECRET not in r.text and PERM_SECRET not in audit_text(c)
    assert c.get(u(cid)).json() == {"active": False}


def test_kaji_token_option_requires_a_kaji_login(client):
    assert client.post("/api/connections/1/admin-session/kaji-token").status_code == 401
    assert client.get("/api/connections/1/admin-session/kaji-token").status_code == 401
