import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.alerts as AL
from app.config import get_settings
from app.crypto import decrypt
from app.db import get_engine
from app.main import app
from app.models import AlertEvent, AlertRule

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
HOOK = "https://hooks.example.org/T000/secret-token-xyz"
OK = {"name": "CPU haut", "kind": "cpu", "threshold": 80, "minutes": 5}
SENT: list[tuple[str, str, dict]] = []
ST: dict = {}


@pytest.fixture
def api(client, monkeypatch):
    SENT.clear(); ST.clear()
    AL.send_webhook  # noqa: B018
    from app.routers import alerts as R
    R._LAST_TEST.clear()

    async def fake_send(url, text, payload):
        SENT.append((url, text, payload))
        return not ST.get("fails")
    monkeypatch.setattr(R.engine, "send_webhook", fake_send)
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    return client, client.post("/api/connections", json=BODY).json()["id"]


def u(cid, tail=""):
    return f"/api/connections/{cid}/alerts{tail}"


def create(c, cid, **over):
    return c.post(u(cid, "/rules"), json={**OK, **over})


def test_create_list_update_delete_and_history_cleanup(api):
    c, cid = api
    r = create(c, cid)
    assert r.status_code == 201
    j = r.json()
    assert j == {"id": j["id"], "name": "CPU haut", "kind": "cpu", "threshold": 80, "minutes": 5, "enabled": True, "has_webhook": False, "created_by": "admin"}
    assert c.get(u(cid, "/rules")).json() == [j]
    r = c.put(u(cid, f"/rules/{j['id']}"), json={**OK, "threshold": 90, "enabled": False})
    assert r.status_code == 200 and r.json()["threshold"] == 90 and r.json()["enabled"] is False
    with Session(get_engine()) as db:
        db.add(AlertEvent(rule_id=j["id"], conn_id=cid, subject="enzo", status="resolved"))
        db.commit()
    assert c.get(u(cid, "/events")).json()[0]["rule"] == "CPU haut"
    assert c.delete(u(cid, f"/rules/{j['id']}")).status_code == 400
    assert c.delete(u(cid, f"/rules/{j['id']}?confirm=true")).json() == {"deleted": j["id"]}
    assert c.get(u(cid, "/rules")).json() == [] and c.get(u(cid, "/events")).json() == []        # l'historique part avec la règle
    t = c.get("/api/audit").text
    assert "alert-rule-create" in t and "alert-rule-update" in t and "alert-rule-delete" in t


@pytest.mark.parametrize("over", [
    {"kind": "inconnu"}, {"kind": "cpu", "threshold": 0}, {"kind": "mem", "threshold": 101}, {"kind": "storage", "threshold": -1}, {"kind": "node_offline", "threshold": 50},
    {"kind": "task_failed", "threshold": 10}, {"minutes": 0}, {"minutes": 121}, {"minutes": "5"}, {"threshold": "80"}, {"threshold": True}, {"name": "ab"}, {"name": "x" * 81},
    {"name": "a\nb c"}, {"enabled": "oui"}, {"webhook_url": "x" * 600}, {"webhook_url": "http://127.0.0.1/x"}, {"webhook_url": "http://localhost/x"}, {"webhook_url": "ftp://example.org/x"},
    {"webhook_url": "pas une url"}, {"webhook_url": "https://u:p@example.org/x"}, {"webhook_url": HOOK, "clear_webhook": True},
])
def test_invalid_rules_are_refused_and_never_echo_the_url(api, over):
    c, cid = api
    r = create(c, cid, **over)
    assert r.status_code == 422 and c.get(u(cid, "/rules")).json() == [] and "secret-token-xyz" not in r.text
    assert "secret-token-xyz" not in c.get("/api/audit").text


def test_the_webhook_is_write_only_and_encrypted(api):
    c, cid = api
    r = create(c, cid, webhook_url=HOOK)
    assert r.status_code == 201 and r.json()["has_webhook"] is True
    for text in (r.text, c.get(u(cid, "/rules")).text, c.get("/api/audit").text):
        assert "secret-token-xyz" not in text and "hooks.example.org" not in text
    with Session(get_engine()) as db:
        enc = db.get(AlertRule, r.json()["id"]).webhook_enc
    assert HOOK not in enc and decrypt(get_settings().kaji_secret_key, enc) == HOOK


def test_updating_keeps_replaces_or_clears_the_webhook(api):
    c, cid = api
    rid = create(c, cid, webhook_url=HOOK).json()["id"]

    def enc():
        with Session(get_engine()) as db:
            return db.get(AlertRule, rid).webhook_enc
    first = enc()
    assert c.put(u(cid, f"/rules/{rid}"), json={**OK, "threshold": 70}).json()["has_webhook"] is True and enc() == first            # inchangée
    c.put(u(cid, f"/rules/{rid}"), json={**OK, "webhook_url": "https://hooks.example.org/autre"})
    assert enc() != first and decrypt(get_settings().kaji_secret_key, enc()).endswith("/autre")
    assert c.put(u(cid, f"/rules/{rid}"), json={**OK, "clear_webhook": True}).json()["has_webhook"] is False and enc() is None


def test_at_most_50_rules_per_connection(api):
    c, cid = api
    with Session(get_engine()) as db:
        for i in range(50):
            db.add(AlertRule(conn_id=cid, name=f"règle {i}", kind="cpu", threshold=80, minutes=5, enabled=True, created_by="admin", cursor=0))
        db.commit()
    r = create(c, cid)
    assert r.status_code == 409 and "50" in r.json()["detail"]


def test_rules_are_isolated_per_connection(api):
    c, cid = api
    other = c.post("/api/connections", json={**BODY, "name": "autre", "host": "10.0.0.6"}).json()["id"]
    rid = create(c, cid).json()["id"]
    assert c.get(u(other, "/rules")).json() == [] and c.get(u(other, "/events")).json() == []
    assert c.put(u(other, f"/rules/{rid}"), json=OK).status_code == 404 and c.delete(u(other, f"/rules/{rid}?confirm=true")).status_code == 404
    assert c.post(u(other, f"/rules/{rid}/test?confirm=true")).status_code == 404 and c.get(u(9999, "/rules")).status_code == 404


def test_events_are_bounded_and_newest_first(api):
    c, cid = api
    rid = create(c, cid).json()["id"]
    with Session(get_engine()) as db:
        for i in range(60):
            db.add(AlertEvent(rule_id=rid, conn_id=cid, subject=f"n{i}", status="resolved"))
        db.commit()
    ev = c.get(u(cid, "/events")).json()
    assert len(ev) == 50 and ev[0]["subject"] == "n59"
    assert len(c.get(u(cid, "/events?limit=5")).json()) == 5 and c.get(u(cid, "/events?limit=0")).status_code == 422 and c.get(u(cid, "/events?limit=201")).status_code == 422


def test_test_message_needs_confirm_a_webhook_and_is_rate_limited(api):
    c, cid = api
    no_hook = create(c, cid).json()["id"]
    assert c.post(u(cid, f"/rules/{no_hook}/test")).status_code == 400
    r0 = c.post(u(cid, f"/rules/{no_hook}/test?confirm=true"))
    assert r0.status_code == 409 and "pas de webhook" in r0.json()["detail"] and not SENT
    rid = create(c, cid, name="Avec webhook", webhook_url=HOOK).json()["id"]
    assert c.post(u(cid, f"/rules/{rid}/test")).status_code == 400 and not SENT
    r = c.post(u(cid, f"/rules/{rid}/test?confirm=true"))
    assert r.status_code == 200 and r.json() == {"sent": True} and SENT[0][0] == HOOK and "TEST" in SENT[0][1] and SENT[0][2]["state"] == "test"
    assert c.post(u(cid, f"/rules/{rid}/test?confirm=true")).status_code == 429 and len(SENT) == 1
    assert "secret-token-xyz" not in c.get("/api/audit").text and "alert-test" in c.get("/api/audit").text


def test_a_failed_test_is_reported_not_hidden(api):
    c, cid = api
    rid = create(c, cid, webhook_url=HOOK).json()["id"]
    ST["fails"] = True
    assert c.post(u(cid, f"/rules/{rid}/test?confirm=true")).json() == {"sent": False}
    assert ("alert-test", "error") in {(a["action"], a["status"]) for a in c.get("/api/audit").json()}


def test_an_unreadable_stored_webhook_is_a_clear_409(api):
    c, cid = api
    rid = create(c, cid, webhook_url=HOOK).json()["id"]
    with Session(get_engine()) as db:
        db.get(AlertRule, rid).webhook_enc = "pas-du-chiffre"
        db.commit()
    r = c.post(u(cid, f"/rules/{rid}/test?confirm=true"))
    assert r.status_code == 409 and not SENT


def test_only_administrators_write(api):
    c, cid = api
    rid = create(c, cid).json()["id"]
    for name, role in (("alice", "viewer"), ("olivier", "operator")):
        c.post("/api/kaji-users", json={"username": name, "password": PWD, "role": role})
        other = TestClient(app)
        assert other.post("/api/auth/login", json={"username": name, "password": PWD}).status_code == 200
        assert other.get(u(cid, "/rules")).status_code == 200 and other.get(u(cid, "/events")).status_code == 200
        assert other.post(u(cid, "/rules"), json=OK).status_code == 403 and other.put(u(cid, f"/rules/{rid}"), json=OK).status_code == 403
        assert other.delete(u(cid, f"/rules/{rid}?confirm=true")).status_code == 403 and other.post(u(cid, f"/rules/{rid}/test?confirm=true")).status_code == 403
    assert len(c.get(u(cid, "/rules")).json()) == 1


def test_requires_a_login(client):
    assert client.get("/api/connections/1/alerts/rules").status_code == 401 and client.post("/api/connections/1/alerts/rules", json=OK).status_code == 401
    assert client.get("/api/connections/1/alerts/events").status_code == 401
