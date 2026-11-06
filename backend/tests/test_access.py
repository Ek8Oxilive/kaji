import httpx
import pytest

from app.accessspec import FEATURES, check_features, granted, needed_paths
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}

USERS = [
    {"userid": "root@pam", "enable": 1, "expire": 0, "realm-type": "pam"},
    {"userid": "kaji@pve", "enable": 1, "expire": 1900000000, "realm-type": "pve"},
    {"userid": "off@pve", "enable": 0},
    {"userid": ""}, {"enable": 1}, "illisible", None,
]
GROUPS = [{"groupid": "admins", "comment": "Admins", "users": "root@pam,kaji@pve"}, {"groupid": "vide"}, {"x": 1}, "?"]
ROLES = [
    {"roleid": "PVEAuditor", "special": 1, "privs": "Sys.Audit,VM.Audit,Pool.Audit"},
    {"roleid": "Mien", "privs": "VM.PowerMgmt,Sys.Audit", "special": 0}, {"roleid": ""}, {"privs": "x"}, "?",
]
ACL = [
    {"path": "/vms", "type": "user", "ugid": "kaji@pve", "roleid": "PVEVMAdmin", "propagate": 1},
    {"path": "/", "type": "user", "ugid": "kaji@pve", "roleid": "PVEAuditor", "propagate": 0},
    {"path": "/", "ugid": "", "roleid": "X"}, {"ugid": "u", "roleid": "r"}, "?",
]
REALMS = [{"realm": "pve", "type": "pve", "comment": "Proxmox VE"}, {"realm": "pam", "type": "pam"}, {"type": "x"}, 5]

ALL_PRIVS = {p: 1 for f in FEATURES for _, privs in f.needs for p in privs}
STATE: dict = {}
SEEN: list[httpx.Request] = []


def _handler(request: httpx.Request) -> httpx.Response:
    SEEN.append(request)
    p = request.url.path.removeprefix("/api2/json")
    if p == "/access/permissions":
        path = request.url.params.get("path")
        if path in STATE.get("fail_paths", ()):
            return httpx.Response(403, json={"data": None})
        if STATE.get("fail_all"):
            return httpx.Response(500, json={"data": None})
        perms = STATE.get("perms", {}).get(path, ALL_PRIVS)
        body = {"/access": {"Sys.Audit": 1}, "/pool/x": {}}      # bruit : Proxmox renvoie d'autres chemins aussi
        if path not in STATE.get("omit_paths", ()):
            body[path] = perms
        return httpx.Response(200, json={"data": STATE.get("raw_perms", body)})
    table = {"/access/users": USERS, "/access/groups": GROUPS, "/access/roles": ROLES, "/access/acl": ACL,
             "/access/domains": REALMS}
    if p in table:
        return httpx.Response(200, json={"data": table[p]})
    return httpx.Response(404, json={"data": None})


@pytest.fixture
def api(client):
    STATE.clear()
    SEEN.clear()
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def get(api, what):
    c, cid = api
    return c.get(f"/api/connections/{cid}/access/{what}")


def feats(api):
    r = get(api, "features")
    assert r.status_code == 200
    return {f["id"]: f for f in r.json()}


# ---------- listes --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("what", ["users", "groups", "roles", "acl", "realms", "features"])
def test_all_routes_require_auth(client, what):
    assert client.get(f"/api/connections/1/access/{what}").status_code == 401


def test_users_shaped_sorted_and_garbage_ignored(api):
    u = get(api, "users").json()
    assert [x["userid"] for x in u] == ["kaji@pve", "off@pve", "root@pam"]
    by = {x["userid"]: x for x in u}
    assert by["kaji@pve"] == {"userid": "kaji@pve", "realm": "pve", "realm_type": "pve", "enabled": True, "expire": 1900000000}
    assert by["root@pam"]["expire"] is None             # 0 = n'expire jamais
    assert by["off@pve"]["enabled"] is False


def test_groups_roles_acl_realms(api):
    assert get(api, "groups").json() == [{"groupid": "admins", "comment": "Admins", "users": ["root@pam", "kaji@pve"]},
                                         {"groupid": "vide", "comment": None, "users": []}]
    r = {x["roleid"]: x for x in get(api, "roles").json()}
    assert r["PVEAuditor"] == {"roleid": "PVEAuditor", "special": True, "privs": ["Pool.Audit", "Sys.Audit", "VM.Audit"]}
    assert r["Mien"]["special"] is False and r["Mien"]["privs"] == ["Sys.Audit", "VM.PowerMgmt"]
    assert get(api, "acl").json() == [
        {"path": "/", "type": "user", "ugid": "kaji@pve", "roleid": "PVEAuditor", "propagate": False},
        {"path": "/vms", "type": "user", "ugid": "kaji@pve", "roleid": "PVEVMAdmin", "propagate": True}]
    assert [x["realm"] for x in get(api, "realms").json()] == ["pam", "pve"]


def test_nothing_is_ever_written_and_no_secret_leaks(api):
    for what in ["users", "groups", "roles", "acl", "realms", "features"]:
        r = get(api, what)
        assert SECRET not in r.text
    assert SEEN and all(req.method == "GET" for req in SEEN)


# ---------- droits de Kaji ------------------------------------------------------------------------------------------

def test_every_feature_ok_when_all_privileges_granted(api):
    f = feats(api)
    assert len(f) == len(FEATURES) and all(x["status"] == "ok" and x["missing"] == [] for x in f.values())


def test_missing_privilege_is_named_with_its_path(api):
    STATE["perms"] = {"/": {k: 1 for k in ALL_PRIVS if k != "Sys.Modify"}}
    f = feats(api)
    assert f["backup-jobs"]["status"] == "missing"
    assert f["backup-jobs"]["missing"] == [{"path": "/", "privilege": "Sys.Modify"}]
    assert f["view"]["status"] == "ok"                          # les autres fonctions ne sont pas touchées


def test_a_feature_needing_two_paths_reports_the_one_that_lacks(api):
    STATE["perms"] = {"/storage": {}}
    f = feats(api)
    assert f["backup"]["status"] == "missing"
    assert f["backup"]["missing"] == [{"path": "/storage", "privilege": "Datastore.AllocateSpace"}]
    assert f["power"]["status"] == "ok"


def test_unreadable_path_is_unknown_never_ok(api):
    STATE["fail_paths"] = {"/sdn/zones"}
    f = feats(api)
    assert f["network"]["status"] == "unknown" and f["network"]["missing"] == []
    assert f["power"]["status"] == "ok"                          # un échec n'en contamine pas un autre


def test_missing_wins_over_unknown(api):
    STATE["fail_paths"] = {"/storage"}
    STATE["perms"] = {"/vms": {k: 1 for k in ALL_PRIVS if k != "VM.Backup"}}
    f = feats(api)["backup"]
    assert f["status"] == "missing" and f["missing"] == [{"path": "/vms", "privilege": "VM.Backup"}]


def test_path_absent_from_the_answer_is_unknown_never_ok(api):
    STATE["omit_paths"] = {"/vms"}
    f = feats(api)
    assert f["power"]["status"] == "unknown" and f["create"]["status"] == "unknown"


@pytest.mark.parametrize("bad", ["1", True, 0, "0", None, 2, 1.5, [1], {}])
def test_only_the_integer_one_counts_as_granted(api, bad):
    STATE["perms"] = {"/": {**ALL_PRIVS, "Sys.Modify": bad}}
    assert feats(api)["backup-jobs"]["status"] == "missing"


def test_garbage_answer_is_unknown(api):
    STATE["raw_perms"] = "n'importe quoi"
    assert all(x["status"] == "unknown" for x in feats(api).values())
    STATE["raw_perms"] = [1, 2]
    assert all(x["status"] == "unknown" for x in feats(api).values())


def test_proxmox_down_returns_the_error_not_a_fake_unknown(api):
    STATE["fail_all"] = True
    assert get(api, "features").status_code in (502, 504)


def test_proxmox_is_only_asked_about_constant_paths(api):
    feats(api)
    asked = {req.url.params.get("path") for req in SEEN if req.url.path.endswith("/access/permissions")}
    assert asked == set(needed_paths()) == {"/", "/pool", "/sdn/zones", "/storage", "/vms"}


# ---------- logique pure --------------------------------------------------------------------------------------------

def test_granted_is_strict():
    assert granted({"A": 1, "B": 0, "C": True, "D": "1"}) == {"A"}
    assert granted("x") is None and granted(None) is None


def test_check_features_without_any_data_is_all_unknown():
    assert {x["status"] for x in check_features({})} == {"unknown"}


def test_check_features_with_empty_privileges_is_all_missing():
    assert {x["status"] for x in check_features({p: set() for p in needed_paths()})} == {"missing"}
