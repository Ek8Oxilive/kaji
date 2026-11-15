"""Rôles par périmètre (lot #447, jalon J2) : un compte restreint ne sort pas de son groupe de machines, décidé par le serveur à chaque requête."""
import asyncio
import re

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import scope
from app.db import get_engine
from app.deps import get_client_factory
from app.main import app
from app.models import AuditLog, UserScope
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
S = {1: frozenset({115, 117})}                                     # périmètre type : la connexion 1, machines 115 et 117
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": "s3cr3t-value-xyz"}
GUESTS = [{"vmid": 115, "name": "web", "type": "qemu", "node": "enzo", "status": "running"},
          {"vmid": 116, "name": "dns", "type": "lxc", "node": "enzo", "status": "running"},
          {"vmid": 117, "name": "db", "type": "qemu", "node": "enzo2", "status": "stopped"}]
UPID = "UPID:enzo:0001:0002:0003:qmstart:{vmid}:root@pam:"


# ---------------------------------------------------------------- la politique (fonction pure)
@pytest.mark.parametrize("method,path", [
    ("GET", "/api/connections/1/guests/enzo/qemu/115"), ("POST", "/api/connections/1/guests/enzo/qemu/115/start"), ("GET", "/api/connections/1/guests/enzo2/qemu/117/options"),
    ("POST", "/api/connections/1/guests/enzo/qemu/115/snapshots"), ("DELETE", "/api/connections/1/guests/enzo/qemu/115/snapshots/s1"),
    ("GET", "/api/connections/1/firewall/guests/enzo/qemu/115"), ("PUT", "/api/connections/1/firewall/guests/enzo2/qemu/117/rules/0"),
    ("GET", "/api/auth/me"), ("POST", "/api/auth/totp/setup"), ("GET", "/api/me/proxmox-tokens"), ("GET", "/api/connections"),
    ("GET", "/api/connections/1/guests"), ("GET", "/api/connections/1/events"),
    ("GET", "/api/connections/1/tasks/enzo/" + UPID.format(vmid=115)), ("GET", "/api/connections/1/tasks/enzo/" + UPID.format(vmid=117) + "/log"),
])
def test_what_a_restricted_account_may_reach(method, path):
    assert scope.allowed(S, method, path)


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/connections/1/guests/enzo/lxc/116"), ("POST", "/api/connections/1/guests/enzo/lxc/116/start"), ("GET", "/api/connections/1/firewall/guests/enzo/lxc/116"),
    ("GET", "/api/connections/2/guests/enzo/qemu/115"), ("GET", "/api/connections/2/guests"), ("GET", "/api/connections/2/events"),
    ("GET", "/api/connections/1/storages"), ("GET", "/api/connections/1/nodes"), ("GET", "/api/connections/1/cluster/status"), ("GET", "/api/connections/1/tasks"),
    ("GET", "/api/connections/1/ha/resources"), ("GET", "/api/connections/1/access/users"), ("GET", "/api/audit"), ("GET", "/api/kaji-users"), ("PUT", "/api/kaji-users/1/scope"),
    ("POST", "/api/connections"), ("DELETE", "/api/connections/1"), ("GET", "/api/connections/1"), ("POST", "/api/connections/1/guests"), ("POST", "/api/connections/1/guests/enzo/qemu"),
    ("GET", "/api/connections/1/tasks/enzo/" + UPID.format(vmid=116)), ("GET", "/api/connections/1/tasks/enzo/" + UPID.format(vmid=116) + "/log"),
    ("DELETE", "/api/connections/1/tasks/enzo/" + UPID.format(vmid=115)),                                              # arrêter une tâche : pas de lecture seule
    ("GET", "/api/connections/1/tasks/enzo/UPID:enzo:0001:0002:0003:aptupdate::root@pam:"),                          # tâche du nœud : pas une machine
    ("GET", "/api/connections/1/tasks/enzo/UPID:enzo:0001:0002:0003:qmstart:abc:root@pam:"),
    ("GET", "/api/connections/1/tasks/enzo/UPID:enzo:0001:0002:0003:cephstartosd:115:root@pam:"), ("GET", "/api/connections/1/tasks/enzo/UPID:enzo:0001:0002:0003:srvreload:115:root@pam:"),
    ("GET", "/api/connections/1/tasks/enzo/UPID:enzo:0001:0002:0003:aptupdate:115:root@pam:/log"),
    ("GET", "/api/health/../connections/1/storages"), ("GET", "/api/connections/1/guests/enzo/qemu/115/../../../116/x"), ("GET", "/api/connections/1/guests/enzo/qemu/115//x"),
    ("GET", "/api/connections/1/guests/enzo/qemu/115/snapshots/é"), ("GET", "/api/connections/1/guests/enzo/qemu/115/x\n"), ("GET", "/api/connections/1/guests/enzo/qemu/115/x\x00"),
    ("GET", "/api/connections/1/guests/enzo/qemu/115/x\t"), ("GET", "/api/connections/1/guests/enzo/qemu/115/\u202ex"), ("GET", "/api/connections/1/guests/enzo/qemu/115/x/../y"),
    ("GET", "/api/connections/1/guests/enzo/qemu/115é"), ("GET", "/api/connections/1/guests/enzo/qemu/115\n"), ("GET", "/api/connections/1/guests/enzo/qemu/115x"),
    ("GET", "/api/connections/1/guests/enzo/qemu/1150"), ("GET", "/api/connections/1/guests/enzo/qemu/15"), ("GET", "/api/connections/1/guests/enzo/qemu/-115"),
    ("GET", "/api/connections/1/guests/enzo/vm/115"), ("GET", "/x/api/connections/1/guests/enzo/qemu/115"), ("GET", "/api/connections/1x/guests/enzo/qemu/115"),
    ("GET", "/api/connections/1/guests/enzo/qemu/115/"), ("GET", "/api/connections/1/guests"), ("GET", ""), ("GET", "/"),
])
def test_everything_else_is_refused(method, path):
    expected_ok = (method, path) == ("GET", "/api/connections/1/guests")
    assert scope.allowed(S, method, path) is expected_ok


def test_the_lists_are_read_only_and_the_connection_list_cannot_be_written():
    for m in ("POST", "PUT", "PATCH", "DELETE"):
        assert not scope.allowed(S, m, "/api/connections/1/guests") and not scope.allowed(S, m, "/api/connections/1/events") and not scope.allowed(S, m, "/api/connections")


def test_filters_keep_only_the_perimeter_and_leak_nothing_of_the_cluster():
    assert [g["vmid"] for g in scope.filter_guests(S, 1, GUESTS)] == [115, 117]
    assert scope.filter_guests(S, 2, GUESTS) == [] and scope.filter_guests(None, 1, GUESTS) == GUESTS
    low = [{"vmid": 1, "name": "a"}, {"vmid": 100, "name": "b"}]
    assert scope.filter_guests(S, 2, low) == [] and scope.machines(S, 2) == frozenset() and scope.machines(None, 2) is None and scope.machines(S, 1) == S[1]
    snap = {"status": {"name": "lab", "quorate": True, "nodes": [{"name": "enzo", "ip": "10.0.0.1"}]},
            "nodes": [{"node": "enzo", "status": "online", "cpu": 0.5}, {"node": "enzo2", "status": "online", "cpu": 0.1}, {"node": "enzo3", "status": "online"}],
            "guests": GUESTS}
    out = scope.filter_snapshot({1: frozenset({115})}, 1, snap)
    assert [g["vmid"] for g in out["guests"]] == [115] and out["nodes"] == [{"node": "enzo", "status": "online"}]
    assert out["status"] == {"name": None, "quorate": None, "nodes": []} and "10.0.0.1" not in str(out) and "enzo3" not in str(out)
    assert scope.filter_snapshot(None, 1, snap) is snap


class C:
    def __init__(self, id):
        self.id = id


def test_connection_filter():
    assert [c.id for c in scope.filter_connections(S, [C(1), C(2)])] == [1] and [c.id for c in scope.filter_connections(None, [C(1), C(2)])] == [1, 2]


# ---------------------------------------------------------------- la garde : TOUTES les routes de l'application passent par la politique
def _routes():
    return sorted((m.upper(), path) for path, item in app.openapi()["paths"].items() for m in item if m in ("get", "post", "put", "patch", "delete"))


def _fill(tpl: str, vmid: int) -> str:
    out = tpl.replace("{conn_id}", "1").replace("{node}", "enzo").replace("{gtype}", "qemu").replace("{vmid}", str(vmid)).replace("{upid}", UPID.format(vmid=vmid))
    return re.sub(r"\{[^}:]+(:[^}]+)?\}", "x1", out)


GUEST_TPL = re.compile(r"/api/connections/\{conn_id\}/(?:firewall/)?guests/\{node\}/(?:\{gtype\}|qemu|lxc)/\{vmid\}(?:/.*)?")
TASK_TPL = re.compile(r"/api/connections/\{conn_id\}/tasks/\{node\}/\{upid\}(?:/log)?")


def _expected(method: str, tpl: str, in_scope: bool) -> bool:
    if tpl.startswith(("/api/auth/", "/api/me/")):
        return True
    if (method, tpl) == ("GET", "/api/connections") or (method == "GET" and tpl in ("/api/connections/{conn_id}/guests", "/api/connections/{conn_id}/events")):
        return True
    if GUEST_TPL.fullmatch(tpl):
        return in_scope
    return method == "GET" and bool(TASK_TPL.fullmatch(tpl)) and in_scope


def test_the_route_list_is_not_empty():
    assert len(_routes()) > 350


@pytest.mark.parametrize("method,tpl", _routes())
def test_every_route_of_the_application_is_refused_unless_explicitly_allowed(method, tpl):
    """Une route ajoutée plus tard est refusée par défaut : seul ce que `_expected` liste passe. Une machine HORS périmètre est refusée sur toutes les routes d'une machine."""
    assert scope.allowed(S, method, _fill(tpl, 115)) is _expected(method, tpl, True), f"{method} {tpl} (dans le périmètre)"
    assert scope.allowed(S, method, _fill(tpl, 999)) is _expected(method, tpl, False), f"{method} {tpl} (hors périmètre)"


# ---------------------------------------------------------------- de bout en bout, sur un faux Proxmox
CALLS: list[tuple[str, str]] = []


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    CALLS.append((request.method, p))
    ok = lambda data: httpx.Response(200, json={"data": data})                                # noqa: E731
    if p == "/cluster/resources":
        return ok(GUESTS)
    if p == "/cluster/status":
        return ok([{"type": "cluster", "name": "lab", "quorate": 1}, {"type": "node", "name": "enzo", "online": 1, "ip": "10.0.0.1"}])
    if p == "/nodes":
        return ok([{"node": "enzo", "status": "online"}, {"node": "enzo2", "status": "online"}])
    if request.method == "POST":
        return ok(UPID.format(vmid=115))
    return ok({"status": "stopped", "lock": None})


@pytest.fixture
def lab(client):
    CALLS.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    c1 = client.post("/api/connections", json=BODY).json()["id"]
    c2 = client.post("/api/connections", json={**BODY, "name": "autre"}).json()["id"]
    ids = {}
    for name, role in (("alice", "operator"), ("vera", "viewer")):
        ids[name] = client.post("/api/kaji-users", json={"username": name, "password": PWD, "role": role}).json()["id"]
    yield client, c1, c2, ids
    app.dependency_overrides.clear()


def login(name):
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": name, "password": PWD}).status_code == 200
    return c


def restrict(admin, uid, conn, vmids):
    r = admin.put(f"/api/kaji-users/{uid}/scope", json={"entries": [{"conn_id": conn, "vmids": vmids}]})
    assert r.status_code == 200, r.text
    return r.json()


def audit_rows(action):
    with Session(get_engine()) as db:
        return db.scalars(select(AuditLog).where(AuditLog.action == action)).all()


def test_an_unrestricted_account_is_unchanged(lab):
    _admin, c1, _c2, _ids = lab
    a = login("alice")
    assert [g["vmid"] for g in a.get(f"/api/connections/{c1}/guests").json()] == [115, 116, 117]
    assert a.get("/api/auth/me").json()["restricted"] is False


def test_a_restricted_account_sees_only_its_machines_and_connections(lab):
    admin, c1, c2, ids = lab
    restrict(admin, ids["alice"], c1, [115])
    a = login("alice")
    assert [g["vmid"] for g in a.get(f"/api/connections/{c1}/guests").json()] == [115]
    assert [c["id"] for c in a.get("/api/connections").json()] == [c1]
    assert a.get(f"/api/connections/{c2}/guests").status_code == 403
    assert a.get("/api/auth/me").json() == {"username": "alice", "role": "operator", "restricted": True}


@pytest.mark.parametrize("path", ["/storages", "/nodes", "/cluster/status", "/tasks", "/ha/resources", "/access/users", "/schedules", "/alerts/rules", "/notifications", "/datacenter/options"])
def test_a_restricted_account_is_refused_every_global_page_and_it_is_audited(lab, path):
    admin, c1, _c2, ids = lab
    restrict(admin, ids["alice"], c1, [115])
    CALLS.clear()
    r = login("alice").get(f"/api/connections/{c1}{path}")
    assert r.status_code == 403 and "périmètre" in r.json()["detail"] and not CALLS                     # refusé AVANT tout appel à Proxmox
    rows = audit_rows("scope-refused")
    assert rows and rows[-1].username == "alice" and path in rows[-1].target and rows[-1].status == "error"


def test_an_operator_acts_on_its_own_machine_only(lab):
    admin, c1, _c2, ids = lab
    restrict(admin, ids["alice"], c1, [115])
    a = login("alice")
    CALLS.clear()
    assert a.post(f"/api/connections/{c1}/guests/enzo/lxc/116/start").status_code == 403 and not CALLS
    assert a.post(f"/api/connections/{c1}/guests/enzo/qemu/115/start").status_code in (200, 202) and any(m == "POST" and "/qemu/115/" in p for m, p in CALLS)
    assert a.post(f"/api/connections/{c1}/guests/enzo/qemu/115/clone", json={}).status_code == 403          # le rôle s'applique EN PLUS : un opérateur ne clone pas
    assert a.delete(f"/api/connections/{c1}/guests/enzo/qemu/115").status_code == 403


def test_a_restricted_viewer_reads_its_machine_but_cannot_act(lab):
    admin, c1, _c2, ids = lab
    restrict(admin, ids["vera"], c1, [115])
    v = login("vera")
    assert v.get(f"/api/connections/{c1}/guests/enzo/qemu/115/options").status_code != 403
    assert v.get(f"/api/connections/{c1}/guests/enzo/lxc/116/options").status_code == 403
    assert v.post(f"/api/connections/{c1}/guests/enzo/qemu/115/start").status_code == 403


def test_a_perimeter_change_applies_immediately_without_a_new_login(lab):
    admin, c1, _c2, ids = lab
    restrict(admin, ids["alice"], c1, [115])
    a = login("alice")
    assert a.get(f"/api/connections/{c1}/guests/enzo/lxc/116/options").status_code == 403
    restrict(admin, ids["alice"], c1, [115, 116])
    assert a.get(f"/api/connections/{c1}/guests/enzo/lxc/116/options").status_code != 403
    restrict(admin, ids["alice"], c1, [116])
    assert a.get(f"/api/connections/{c1}/guests/enzo/qemu/115/options").status_code == 403
    assert admin.delete(f"/api/kaji-users/{ids['alice']}/scope?confirm=true&name=alice").status_code == 200
    assert a.get(f"/api/connections/{c1}/storages").status_code != 403                                         # plus de restriction : la politique du rôle


def test_an_administrator_is_never_restricted_even_with_stray_rows(lab):
    admin, c1, _c2, _ids = lab
    with Session(get_engine()) as db:
        db.add(UserScope(user_id=1, conn_id=c1, vmid=115))
        db.commit()
    assert [g["vmid"] for g in admin.get(f"/api/connections/{c1}/guests").json()] == [115, 116, 117]
    assert admin.get("/api/auth/me").json()["restricted"] is False and admin.get(f"/api/connections/{c1}/storages").status_code != 403


def test_the_task_log_of_another_machine_is_refused(lab):
    admin, c1, _c2, ids = lab
    restrict(admin, ids["vera"], c1, [115])
    v = login("vera")
    assert v.get(f"/api/connections/{c1}/tasks/enzo/{UPID.format(vmid=116)}").status_code == 403
    assert v.get(f"/api/connections/{c1}/tasks/enzo/{UPID.format(vmid=115)}").status_code != 403


# ---------------------------------------------------------------- le flux temps réel
def test_the_event_stream_of_a_restricted_account_has_its_own_filtered_channel(lab, monkeypatch):
    from app.routers import live
    admin, c1, _c2, ids = lab
    restrict(admin, ids["alice"], c1, [115])
    seen = {}

    async def fake_stream(h, key, fetch, heartbeat=15):
        seen["key"], seen["fetch"] = key, fetch
        yield "retry: 1\n\n"

    monkeypatch.setattr(live, "stream", fake_stream)
    login("alice").get(f"/api/connections/{c1}/events")
    assert seen["key"] == (c1, 0, "scope", ids["alice"])                                  # jamais le canal commun (l'état complet serait diffusé)
    snap = asyncio.run(seen["fetch"]())                                                    # l'interrogateur du compte restreint est filtré
    assert [g["vmid"] for g in snap["guests"]] == [115] and snap["status"]["nodes"] == [] and all("ip" not in n for n in snap["nodes"])
    admin.get(f"/api/connections/{c1}/events")
    assert [g["vmid"] for g in asyncio.run(seen["fetch"]())["guests"]] == [115, 116, 117]     # et celui d'un administrateur ne l'est pas
    shared = {}
    monkeypatch.setattr(live, "stream", lambda h, key, fetch, heartbeat=15: (shared.update(key=key) or fake_stream(h, key, fetch)))
    admin.get(f"/api/connections/{c1}/events")
    assert shared["key"] == c1


def test_the_scoped_fetch_filters_every_poll_and_stops_when_the_perimeter_disappears(lab):
    admin, c1, _c2, ids = lab
    restrict(admin, ids["alice"], c1, [115])

    async def inner():
        return {"status": {"name": "lab", "quorate": True, "nodes": []}, "nodes": [{"node": "enzo", "status": "online"}], "guests": GUESTS}

    run = scope.__dict__  # noqa: F841 - le module est importé pour la lisibilité
    from app.routers.live import scoped_fetch
    snap = asyncio.run(scoped_fetch(inner, c1, ids["alice"])())
    assert [g["vmid"] for g in snap["guests"]] == [115]
    assert admin.delete(f"/api/kaji-users/{ids['alice']}/scope?confirm=true&name=alice").status_code == 200
    assert asyncio.run(scoped_fetch(inner, c1, ids["alice"])())["guests"] == []             # plus de restriction : l'ancien flux ne diffuse JAMAIS l'état complet


# ---------------------------------------------------------------- la gestion du périmètre
def test_the_perimeter_api_validates_everything(lab):
    admin, c1, c2, ids = lab
    uid = ids["alice"]
    put = lambda body: admin.put(f"/api/kaji-users/{uid}/scope", json=body)                  # noqa: E731
    for bad in ({}, {"entries": []}, {"entries": [{"conn_id": c1, "vmids": []}]}, {"entries": [{"conn_id": c1, "vmids": [0]}]}, {"entries": [{"conn_id": c1, "vmids": [-1]}]},
                {"entries": [{"conn_id": c1, "vmids": [True]}]}, {"entries": [{"conn_id": c1, "vmids": [115, 115]}]}, {"entries": [{"conn_id": c1, "vmids": ["115"]}]},
                {"entries": [{"conn_id": c1, "vmids": [1_000_000_000]}]}, {"entries": [{"conn_id": 0, "vmids": [115]}]},
                {"entries": [{"conn_id": c1, "vmids": list(range(1, 502))}]}, {"entries": [{"conn_id": c1, "vmids": [115]}] * 21}):
        assert put(bad).status_code == 422, bad
    assert put({"entries": [{"conn_id": c1, "vmids": [115]}, {"conn_id": c1, "vmids": [116]}]}).status_code == 422          # connexion en double
    assert put({"entries": [{"conn_id": 999, "vmids": [115]}]}).status_code == 422                                          # connexion inconnue
    assert admin.get(f"/api/kaji-users/{uid}/scope").json() == {"restricted": False, "entries": []}                        # rien n'a été écrit
    assert put({"entries": [{"conn_id": c1, "vmids": [117, 115]}, {"conn_id": c2, "vmids": [3]}]}).json() == {"restricted": True, "entries": [{"conn_id": c1, "vmids": [115, 117]}, {"conn_id": c2, "vmids": [3]}]}
    assert put({"entries": [{"conn_id": c1, "vmids": [116]}]}).json()["entries"] == [{"conn_id": c1, "vmids": [116]}]         # remplace, n'ajoute pas


def test_an_administrator_cannot_get_a_perimeter_and_an_empty_one_never_widens(lab):
    admin, c1, _c2, ids = lab
    assert admin.put("/api/kaji-users/1/scope", json={"entries": [{"conn_id": c1, "vmids": [115]}]}).status_code == 409
    restrict(admin, ids["alice"], c1, [115])
    assert admin.put(f"/api/kaji-users/{ids['alice']}/scope", json={"entries": []}).status_code == 422
    assert admin.get(f"/api/kaji-users/{ids['alice']}/scope").json()["restricted"] is True                                   # toujours restreint
    assert admin.put("/api/kaji-users/9999/scope", json={"entries": [{"conn_id": c1, "vmids": [1]}]}).status_code == 404
    assert admin.get("/api/kaji-users/9999/scope").status_code == 404


def test_clearing_a_perimeter_needs_confirmation_and_the_name(lab):
    admin, c1, _c2, ids = lab
    uid = ids["alice"]
    assert admin.delete(f"/api/kaji-users/{uid}/scope?confirm=true&name=alice").status_code == 409                          # rien à retirer
    restrict(admin, uid, c1, [115])
    assert admin.delete(f"/api/kaji-users/{uid}/scope").status_code == 400
    assert admin.delete(f"/api/kaji-users/{uid}/scope?confirm=true&name=bob").status_code == 400
    assert admin.get(f"/api/kaji-users/{uid}/scope").json()["restricted"] is True
    assert admin.delete(f"/api/kaji-users/{uid}/scope?confirm=true&name=alice").json() == {"restricted": False, "entries": []}
    assert admin.delete("/api/kaji-users/9999/scope?confirm=true&name=x").status_code == 404


def test_only_an_administrator_manages_perimeters(lab):
    admin, c1, _c2, ids = lab
    a = login("alice")
    body = {"entries": [{"conn_id": c1, "vmids": [115]}]}
    assert a.put(f"/api/kaji-users/{ids['vera']}/scope", json=body).status_code == 403 and a.get(f"/api/kaji-users/{ids['vera']}/scope").status_code == 403
    assert a.delete(f"/api/kaji-users/{ids['vera']}/scope?confirm=true&name=vera").status_code == 403
    restrict(admin, ids["alice"], c1, [115])
    assert login("alice").put(f"/api/kaji-users/{ids['alice']}/scope", json=body).status_code == 403                         # pas de s'élargir soi-même


def test_the_users_list_says_who_is_restricted(lab):
    admin, c1, _c2, ids = lab
    restrict(admin, ids["alice"], c1, [115])
    assert {u["username"]: u["scoped"] for u in admin.get("/api/kaji-users").json()} == {"admin": False, "alice": True, "vera": False}


def test_promoting_to_administrator_removes_the_perimeter_and_deleting_a_user_removes_it_too(lab):
    admin, c1, _c2, ids = lab
    restrict(admin, ids["alice"], c1, [115])
    assert admin.put(f"/api/kaji-users/{ids['alice']}", json={"role": "admin"}).status_code == 200
    with Session(get_engine()) as db:
        assert db.scalars(select(UserScope).where(UserScope.user_id == ids["alice"])).all() == []                         # sinon il réapparaîtrait à la rétrogradation
    assert admin.put(f"/api/kaji-users/{ids['alice']}", json={"role": "operator"}).status_code == 200
    assert admin.get(f"/api/kaji-users/{ids['alice']}/scope").json()["restricted"] is False
    restrict(admin, ids["vera"], c1, [115])
    assert admin.delete(f"/api/kaji-users/{ids['vera']}?confirm=true&name=vera").status_code == 200
    with Session(get_engine()) as db:
        assert db.scalars(select(UserScope).where(UserScope.user_id == ids["vera"])).all() == []


def test_perimeter_changes_are_audited_without_machine_ids_leaking_into_other_logs(lab):
    admin, c1, _c2, ids = lab
    restrict(admin, ids["alice"], c1, [115, 116])
    admin.delete(f"/api/kaji-users/{ids['alice']}/scope?confirm=true&name=alice")
    admin.put("/api/kaji-users/1/scope", json={"entries": [{"conn_id": c1, "vmids": [115]}]})
    assert [r.status for r in audit_rows("kaji-user-scope")] == ["started", "error"]
    assert audit_rows("kaji-user-scope")[0].detail == "périmètre : 2 machine(s) sur 1 connexion(s)"
    assert [r.status for r in audit_rows("kaji-user-scope-clear")] == ["started"]


def test_the_database_alone_cannot_hold_a_duplicate_machine(lab):
    from sqlalchemy.exc import IntegrityError
    _admin, c1, _c2, ids = lab
    with Session(get_engine()) as db:
        db.add(UserScope(user_id=ids["alice"], conn_id=c1, vmid=115))
        db.commit()
        db.add(UserScope(user_id=ids["alice"], conn_id=c1, vmid=115))
        with pytest.raises(IntegrityError):
            db.commit()
