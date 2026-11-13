import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.alerts as AL
from app import alertspec as S
from app.config import get_settings
from app.crypto import encrypt
from app.db import get_engine
from app.models import AlertEvent, AlertRule
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
T0 = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
HOOK = "https://hooks.example.org/T000/secret-token-xyz"
ST: dict = {}
SENT: list[tuple[str, str, dict]] = []


def node(name="enzo", cpu=0.1, mem=10, maxmem=100, status="online"):
    return {"type": "node", "node": name, "status": status, "cpu": cpu, "mem": mem, "maxmem": maxmem}


def store(name="local-lvm", node_="enzo", disk=10, maxdisk=100, status="available"):
    return {"type": "storage", "storage": name, "node": node_, "status": status, "disk": disk, "maxdisk": maxdisk}


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    if ST.get("down"):
        return httpx.Response(500, json={"data": None, "message": SECRET})
    if p == "/cluster/resources":
        return httpx.Response(200, json={"data": ST.get("res", [node()])})
    if p == "/cluster/tasks":
        return httpx.Response(200, json={"data": ST.get("tasks", [])})
    return httpx.Response(404, json={"data": None})


def factory(**kw):
    return ProxmoxClient(**kw, transport=httpx.MockTransport(_handler))


async def notifier(url, text, payload):
    SENT.append((url, text, payload))
    return not ST.get("hook_fails")


@pytest.fixture
def env(client):
    ST.clear(); SENT.clear()
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    return client.post("/api/connections", json=BODY).json()["id"]


def rule(cid, **over):
    row = dict(conn_id=cid, name="CPU haut", kind="cpu", threshold=80, minutes=5, enabled=True, created_by="admin", cursor=0)
    with Session(get_engine()) as db:
        r = AlertRule(**{**row, **over})
        db.add(r)
        db.commit()
        return r.id


def run(now=T0):
    with Session(get_engine()) as db:
        return asyncio.run(AL.evaluate(db, factory, now, notifier))


def events(rid=None):
    with Session(get_engine()) as db:
        q = select(AlertEvent).order_by(AlertEvent.id)
        return [(e.subject, e.status, e.value, e.detail) for e in db.scalars(q) if rid is None or e.rule_id == rid]


# ------------------------------------------------------------------ cycle d'une alerte à seuil
def test_cpu_alert_needs_the_whole_duration_then_fires_then_resolves(env, client):
    rid = rule(env, webhook_enc=encrypt(get_settings().kaji_secret_key, HOOK))
    ST["res"] = [node(cpu=0.93)]
    assert run(T0) == [] and events() == [("enzo", "pending", 93, None)] and not SENT
    assert run(T0 + timedelta(minutes=4)) == [] and not SENT
    out = run(T0 + timedelta(minutes=5))
    assert out == [{"rule": rid, "subject": "enzo", "state": "firing", "value": 93}] and events()[0][1] == "firing"
    assert SENT[0][0] == HOOK and "ALERTE" in SENT[0][1] and "CPU 93 %" in SENT[0][1] and SENT[0][2]["state"] == "firing"
    assert run(T0 + timedelta(minutes=6)) == [] and len(SENT) == 1                      # toujours en alerte : pas de nouvelle notification
    ST["res"] = [node(cpu=0.2)]
    out = run(T0 + timedelta(minutes=7))
    assert out[0]["state"] == "resolved" and events()[0][1] == "resolved" and len(SENT) == 2 and "RÉSOLU" in SENT[1][1]
    t = client.get("/api/audit").text
    assert "alert-firing" in t and "alert-resolved" in t and "alertes" in t and HOOK not in t and "secret-token-xyz" not in t


def test_a_blip_shorter_than_the_duration_never_alerts(env):
    rule(env)
    ST["res"] = [node(cpu=0.95)]
    run(T0)
    ST["res"] = [node(cpu=0.1)]
    assert run(T0 + timedelta(minutes=2)) == [] and events() == [] and not SENT          # la ligne pending est supprimée
    ST["res"] = [node(cpu=0.95)]
    run(T0 + timedelta(minutes=3))
    assert run(T0 + timedelta(minutes=7))[:0] == [] and events()[0][1] == "pending"       # le compte repart de zéro


def test_threshold_is_inclusive_and_per_subject(env):
    rule(env, minutes=1)
    ST["res"] = [node("a", cpu=0.80), node("b", cpu=0.79), node("c", cpu=0.99)]
    run(T0)
    out = run(T0 + timedelta(minutes=1))
    assert {o["subject"] for o in out} == {"a", "c"}


def test_offline_nodes_are_not_counted_for_cpu_and_mem(env):
    rule(env, minutes=1); rule(env, kind="mem", name="RAM", threshold=50, minutes=1)
    ST["res"] = [node("a", cpu=0.99, mem=99, status="offline")]
    run(T0)
    assert run(T0 + timedelta(minutes=1)) == [] and events() == []


def test_mem_storage_and_offline_rules(env):
    r1 = rule(env, kind="mem", name="RAM", threshold=90, minutes=1)
    r2 = rule(env, kind="storage", name="Disque", threshold=85, minutes=1)
    r3 = rule(env, kind="node_offline", name="Hors ligne", threshold=0, minutes=1)
    ST["res"] = [node("a", mem=95), node("b", status="offline"), store(disk=90), store("sauv", "a", 50), store("hs", "a", 99, status="unavailable")]
    run(T0)
    out = {(o["rule"], o["subject"]) for o in run(T0 + timedelta(minutes=1))}
    assert out == {(r1, "a"), (r2, "local-lvm@enzo"), (r3, "b")}                          # stockage « unavailable » ignoré, 50 % sous le seuil


def test_a_missing_subject_resolves_the_alert(env):
    rule(env, kind="storage", name="Disque", threshold=85, minutes=1)
    ST["res"] = [store(disk=95)]
    run(T0); run(T0 + timedelta(minutes=1))
    ST["res"] = []                                                                       # le stockage a disparu
    assert run(T0 + timedelta(minutes=2))[0]["state"] == "resolved"


def test_an_unreachable_connection_changes_nothing(env):
    rule(env, minutes=1)
    ST["res"] = [node(cpu=0.95)]
    run(T0); run(T0 + timedelta(minutes=1))
    ST["down"] = True
    assert run(T0 + timedelta(minutes=2)) == [] and events()[0][1] == "firing"          # ni résolue ni rejouée à tort
    ST.pop("down")
    ST["res"] = [node(cpu=0.95)]
    assert run(T0 + timedelta(minutes=3)) == [] and len(SENT) == 0                       # (pas de webhook configuré)


def test_disabled_rules_and_unknown_kinds_are_ignored(env):
    rule(env, enabled=False, minutes=1)
    rule(env, kind="inconnu", minutes=1)
    ST["res"] = [node(cpu=0.99)]
    run(T0)
    assert run(T0 + timedelta(minutes=1)) == [] and events() == []


# ------------------------------------------------------------------ tâches en échec
def task(end, status="command 'x' failed", type_="vzdump", node_="enzo", id_="105"):
    return {"endtime": end, "status": status, "type": type_, "node": node_, "id": id_, "upid": "UPID:x"}


def test_failed_tasks_alert_once_and_never_replay_history(env):
    rid = rule(env, kind="task_failed", name="Échecs", threshold=0)
    e0 = int(T0.timestamp())
    ST["tasks"] = [task(e0 - 100), task(e0 - 50, "OK"), task(e0 - 40, "WARNINGS: 2"), {"type": "x", "node": "enzo"}]
    assert run() == [] and events() == []                                                # première passe : on se cale, pas d'historique
    assert run() == []
    ST["tasks"] += [task(e0 + 10, "OK"), task(e0 + 20), task(e0 + 30, "WARNINGS: 1"), task(e0 + 40, "unexpected status", "qmstart", id_="115")]
    out = run()
    assert [o["subject"] for o in out] == ["vzdump 105@enzo", "qmstart 115@enzo"] and all(o["state"] == "firing" for o in out)
    assert [e[1] for e in events(rid)] == ["resolved", "resolved"] and events(rid)[1][3] == "unexpected status"
    assert run() == []                                                                   # pas de rejeu


def test_task_alerts_are_bounded_per_pass(env):
    rule(env, kind="task_failed", name="Échecs", threshold=0)
    e0 = int(T0.timestamp())
    run()
    ST["tasks"] = [task(e0 + 1 + i, id_=str(i)) for i in range(60)]
    ST["tasks"].insert(0, task(e0 - 1))
    run()
    assert len(events()) == 0                                                            # le curseur était à 0 : première passe = calage sur la tâche la plus récente
    ST["tasks"] = [task(e0 + 100 + i, id_=str(i)) for i in range(60)]
    assert len(run()) == 20


# ------------------------------------------------------------------ notification
def test_a_failing_webhook_is_noted_without_the_url(env):
    rule(env, minutes=1, webhook_enc=encrypt(get_settings().kaji_secret_key, HOOK))
    ST["res"] = [node(cpu=0.95)]; ST["hook_fails"] = True
    run(); run(T0 + timedelta(minutes=1))
    assert events()[0][3] == "notification échouée" and "secret-token-xyz" not in str(events())


def test_an_unreadable_webhook_does_not_break_the_cycle(env):
    rule(env, minutes=1, webhook_enc="pas-du-chiffre")
    ST["res"] = [node(cpu=0.95)]
    run(); out = run(T0 + timedelta(minutes=1))
    assert out[0]["state"] == "firing" and events()[0][3] == "adresse du webhook illisible" and not SENT


def test_one_broken_rule_does_not_stop_the_others(env, monkeypatch):
    bad = rule(env, minutes=1, name="cassée")
    good = rule(env, minutes=1, name="saine", kind="mem", threshold=50)
    ST["res"] = [node(cpu=0.95, mem=90)]
    real = AL._threshold_rule

    async def flaky(db, notifier_, r, m, now, out):
        if r.id == bad:
            raise RuntimeError("boum")
        return await real(db, notifier_, r, m, now, out)
    monkeypatch.setattr(AL, "_threshold_rule", flaky)
    run(); out = run(T0 + timedelta(minutes=1))
    assert [o["rule"] for o in out] == [good]


# ------------------------------------------------------------------ envoi réel (HTTP simulé)
def _with_transport(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(AL.httpx, "AsyncClient", lambda **kw: real(**kw, transport=httpx.MockTransport(handler)))


def test_send_webhook_posts_json_and_reports_success(monkeypatch):
    seen = []

    def h(request):
        seen.append(request)
        return httpx.Response(200)
    _with_transport(monkeypatch, h)
    assert asyncio.run(AL.send_webhook(HOOK, "texte", {"rule": "r"})) is True
    body = json.loads(seen[0].content)
    assert body == {"text": "texte", "kaji": {"rule": "r"}} and seen[0].method == "POST"


def test_send_webhook_failures_are_quiet_and_local_addresses_never_called(monkeypatch):
    calls = []

    def h(request):
        calls.append(request)
        return httpx.Response(500)
    _with_transport(monkeypatch, h)
    assert asyncio.run(AL.send_webhook(HOOK, "t", {})) is False and len(calls) == 1
    calls.clear()
    for bad in ("http://127.0.0.1/x", "http://localhost/x", "ftp://example.org/x", "pas une url", "http://0.0.0.0/x", "http://169.254.169.254/x"):
        assert asyncio.run(AL.send_webhook(bad, "t", {})) is False
    assert not calls

    def boom(request):
        raise httpx.ConnectError("injoignable")
    _with_transport(monkeypatch, boom)
    assert asyncio.run(AL.send_webhook(HOOK, "t", {})) is False


def test_redirects_are_not_followed(monkeypatch):
    calls = []

    def h(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/interne"})
    _with_transport(monkeypatch, h)
    assert asyncio.run(AL.send_webhook(HOOK, "t", {})) is False and len(calls) == 1


# ------------------------------------------------------------------ mesures hostiles
def test_hostile_resources_are_neutralised():
    m = S.read_measures([None, "x", {"type": "node"}, {"type": "node", "node": 5}, node("ok\n", cpu=True, mem=True, maxmem=True),
                         node("n", cpu=-1, mem=5, maxmem=0), node("big", cpu=7.0, mem=500, maxmem=100), store(disk="x"), store(disk=1, maxdisk=0)])
    assert m["nodes"]["ok "] == {"online": True, "cpu": None, "mem": None}
    assert m["nodes"]["n"] == {"online": True, "cpu": None, "mem": None} and m["nodes"]["big"]["cpu"] == 100 and m["nodes"]["big"]["mem"] == 100 and m["storages"] == {}
    assert S.read_measures(None) == {"nodes": {}, "storages": {}} and S.read_measures({"a": 1}) == {"nodes": {}, "storages": {}}
