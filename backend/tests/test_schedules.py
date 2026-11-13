import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import get_engine
from app.deps import get_client_factory
from app.main import app
from app.models import ScheduledAction
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
OK = {"node": "enzo", "gtype": "qemu", "vmid": 115, "action": "start", "days": [0, 2], "time": "07:30", "timezone": "Europe/Paris"}
ST: dict = {}
SEEN: list[httpx.Request] = []


def _handler(request: httpx.Request) -> httpx.Response:
    SEEN.append(request)
    p = request.url.path.removeprefix("/api2/json")
    if request.method == "GET" and p.startswith("/nodes/enzo/") and p.endswith("/status/current"):
        if ST.get("missing"):
            return httpx.Response(500, json={"data": None, "message": SECRET})
        return httpx.Response(200, json={"data": {"status": "stopped", **({"template": 1} if ST.get("template") else {})}})
    return httpx.Response(404, json={"data": None})


@pytest.fixture
def api(client):
    ST.clear(); SEEN.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def u(cid, tail=""):
    return f"/api/connections/{cid}/schedules{tail}"


def create(c, cid, **over):
    return c.post(u(cid), json={**OK, **over})


def test_create_list_update_delete(api):
    c, cid = api
    r = create(c, cid)
    assert r.status_code == 201
    j = r.json()
    assert j["action"] == "start" and j["days"] == [0, 2] and j["time"] == "07:30" and j["enabled"] is True and j["created_by"] == "admin" and j["next_run"]
    assert c.get(u(cid)).json() == [j]
    r = c.put(u(cid, f"/{j['id']}"), json={**OK, "action": "shutdown", "time": "22:00", "enabled": False})
    assert r.status_code == 200 and r.json()["action"] == "shutdown" and r.json()["time"] == "22:00" and r.json()["enabled"] is False and r.json()["next_run"] is None
    assert c.delete(u(cid, f"/{j['id']}")).status_code == 400
    assert c.delete(u(cid, f"/{j['id']}?confirm=true")).json() == {"deleted": j["id"]}
    assert c.get(u(cid)).json() == []
    t = c.get("/api/audit").text
    assert "schedule-create" in t and "schedule-update" in t and "schedule-delete" in t


def test_days_are_sorted_and_stored(api):
    c, cid = api
    assert create(c, cid, days=[6, 0, 3]).json()["days"] == [0, 3, 6]
    assert create(c, cid, days=[1, 1]).status_code == 422


@pytest.mark.parametrize("over", [{"action": "delete"}, {"action": "migrate"}, {"time": "25:00"}, {"days": []}, {"days": [9]}, {"vmid": 5}, {"gtype": "ct"},
                                  {"node": "a b"}, {"enabled": "oui"}])
def test_invalid_bodies_never_reach_proxmox(api, over):
    c, cid = api
    assert create(c, cid, **over).status_code == 422 and not SEEN and c.get(u(cid)).json() == []


def test_unknown_timezone_is_refused(api):
    c, cid = api
    r = create(c, cid, timezone="Mars/Base")
    assert r.status_code == 422 and "Fuseau" in r.json()["detail"] and not SEEN
    assert create(c, cid, timezone="../etc").status_code == 422


def test_protected_machines_are_refused(api, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "kaji_protected_vmids", "115")
    c, cid = api
    r = create(c, cid)
    assert r.status_code == 403 and "protégée" in r.json()["detail"] and not SEEN and c.get(u(cid)).json() == []


def test_forced_stop_needs_confirm(api):
    c, cid = api
    assert create(c, cid, action="stop").status_code == 400 and c.get(u(cid)).json() == []
    assert create(c, cid, action="stop", confirm=True).status_code == 201


def test_unknown_machine_and_templates_are_refused_without_leak(api):
    c, cid = api
    ST["missing"] = True
    r = create(c, cid)
    assert r.status_code == 422 and SECRET not in r.text and SECRET not in c.get("/api/audit").text
    ST.clear(); ST["template"] = True
    assert create(c, cid).status_code == 409


def test_at_most_200_per_connection(api):
    c, cid = api
    with Session(get_engine()) as db:
        for i in range(200):
            db.add(ScheduledAction(conn_id=cid, node="enzo", gtype="qemu", vmid=200 + i, action="start", days="0", time="07:30", timezone="UTC", enabled=True, created_by="admin"))
        db.commit()
    r = create(c, cid)
    assert r.status_code == 409 and "200" in r.json()["detail"]


def test_schedules_are_isolated_per_connection(api):
    c, cid = api
    other = c.post("/api/connections", json={**BODY, "name": "autre", "host": "10.0.0.6"}).json()["id"]
    sid = create(c, cid).json()["id"]
    assert c.get(u(other)).json() == []
    assert c.put(u(other, f"/{sid}"), json=OK).status_code == 404 and c.delete(u(other, f"/{sid}?confirm=true")).status_code == 404
    assert c.get(u(9999)).status_code == 404 and c.get(u(cid)).json()[0]["id"] == sid


def test_updating_resets_the_remembered_minute(api):
    c, cid = api
    sid = create(c, cid).json()["id"]
    with Session(get_engine()) as db:
        db.get(ScheduledAction, sid).last_key = "2026-11-16 07:30"
        db.commit()
    c.put(u(cid, f"/{sid}"), json=OK)
    with Session(get_engine()) as db:
        assert db.get(ScheduledAction, sid).last_key is None


def test_only_administrators_write(api):
    c, cid = api
    sid = create(c, cid).json()["id"]
    for name, role in (("alice", "viewer"), ("olivier", "operator")):
        c.post("/api/kaji-users", json={"username": name, "password": PWD, "role": role})
        other = TestClient(app)
        assert other.post("/api/auth/login", json={"username": name, "password": PWD}).status_code == 200
        assert other.get(u(cid)).status_code == 200                                   # la lecture reste permise
        assert other.post(u(cid), json=OK).status_code == 403
        assert other.put(u(cid, f"/{sid}"), json=OK).status_code == 403
        assert other.delete(u(cid, f"/{sid}?confirm=true")).status_code == 403
    assert len(c.get(u(cid)).json()) == 1


def test_requires_a_login(client):
    assert client.get("/api/connections/1/schedules").status_code == 401 and client.post("/api/connections/1/schedules", json=OK).status_code == 401
