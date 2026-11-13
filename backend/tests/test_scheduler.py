import asyncio
import re
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import ScheduledAction
from app.proxmox import ProxmoxClient
from app.scheduler import run_due

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
MON_0730_PARIS = datetime(2026, 11, 16, 6, 30, tzinfo=timezone.utc)           # lundi 07:30 à Paris (UTC+1)
CALLS: list[tuple[str, str, str]] = []
ST: dict = {}


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    CALLS.append((request.method, p, request.content.decode()))
    tm = re.fullmatch(r"/nodes/enzo/tasks/(UPID:[^/]+)/status", p)
    if tm:                                                                       # suivi de la tâche lancée
        ST["polls"] = ST.get("polls", 0) + 1
        mode = ST.get("task", "ok")
        if mode == "unreadable":
            return httpx.Response(500, json={"data": None, "message": SECRET})
        if mode == "running":
            return httpx.Response(200, json={"data": {"status": "running"}})
        if mode == "running-then-ok":
            return httpx.Response(200, json={"data": {"status": "running"} if ST["polls"] < 3 else {"status": "stopped", "exitstatus": "OK"}})
        exit_status = {"ok": "OK", "warn": "WARNINGS: 2", "failed": "NUMA needs to be enabled for memory hotplug", "empty": ""}[mode]
        return httpx.Response(200, json={"data": {"status": "stopped", "exitstatus": exit_status}})
    m = re.fullmatch(r"/nodes/enzo/(qemu|lxc)/(\d+)/(status/current|status/(start|shutdown|reboot|stop)|snapshot)", p)
    if not m:
        return httpx.Response(404, json={"data": None, "message": "route inconnue"})
    if ST.get("fail"):
        return httpx.Response(403, json={"data": None, "message": SECRET})
    if p.endswith("status/current"):
        return httpx.Response(200, json={"data": {"status": ST.get("state", "stopped"), **({"template": 1} if ST.get("template") else {})}})
    if request.method != "POST":
        return httpx.Response(501, json={"data": None})
    if p.endswith("/snapshot") and not re.fullmatch(r"snapname=kaji-\d{8}-\d{4}", request.content.decode()):
        return httpx.Response(400, json={"data": None, "message": "snapname invalide"})
    return httpx.Response(200, json={"data": "UPID:enzo:0001:0002:0003:qmstart:115:kaji@pve!kaji:"})


def factory(**kw):
    return ProxmoxClient(**kw, transport=httpx.MockTransport(_handler))


@pytest.fixture
def env(client, monkeypatch):
    import app.scheduler as sch
    monkeypatch.setattr(sch, "FOLLOW_EVERY", 0.005)                             # attentes minuscules dans les tests
    monkeypatch.setattr(sch, "FOLLOW_SECONDS", 0.1)
    CALLS.clear(); ST.clear()
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    return cid


def add(cid, **over):
    row = dict(conn_id=cid, node="enzo", gtype="qemu", vmid=115, action="start", days="0", time="07:30", timezone="Europe/Paris", enabled=True, created_by="admin")
    with Session(get_engine()) as db:
        s = ScheduledAction(**{**row, **over})
        db.add(s)
        db.commit()
        return s.id


def run(now=MON_0730_PARIS):
    with Session(get_engine()) as db:
        return asyncio.run(run_due(db, factory, now))


def row(sid):
    with Session(get_engine()) as db:
        s = db.get(ScheduledAction, sid)
        return s.last_status, s.last_detail, s.last_key


def posts():
    return [c for c in CALLS if c[0] == "POST"]


def test_a_due_start_runs_once_and_is_audited(env, client):
    sid = add(env)
    r = run()
    assert r == [{"id": sid, "status": "ok", "detail": "start"}] and posts() == [("POST", "/nodes/enzo/qemu/115/status/start", "")]
    assert run() == [] and len(posts()) == 1                                    # même minute : jamais rejouée
    assert row(sid)[2] == "2026-11-16 07:30"
    t = client.get("/api/audit").text
    assert "schedule-start" in t and "planificateur" in t


def test_nothing_runs_when_not_due_or_disabled(env):
    add(env, time="07:31"); add(env, days="1"); add(env, enabled=False)
    assert run() == [] and not CALLS


def test_next_week_runs_again(env):
    sid = add(env)
    run()
    assert run(datetime(2026, 11, 23, 6, 30, tzinfo=timezone.utc))[0]["id"] == sid and len(posts()) == 2


def test_start_is_skipped_when_already_running_and_stop_when_already_stopped(env):
    a = add(env)
    ST["state"] = "running"
    assert run()[0]["status"] == "skipped" and not posts()
    b = add(env, action="shutdown", vmid=116)
    ST["state"] = "stopped"
    out = {r["id"]: r for r in run(datetime(2026, 11, 23, 6, 30, tzinfo=timezone.utc))}
    assert out[b]["status"] == "skipped" and out[b]["detail"] == "déjà arrêtée" and out[a]["status"] == "ok"
    assert [c[1] for c in posts()] == ["/nodes/enzo/qemu/115/status/start"]                # seul le démarrage de `a` part ; l'arrêt de `b` est ignoré


def test_each_power_action_uses_the_right_route(env):
    ST["state"] = "running"
    for i, act in enumerate(("shutdown", "reboot", "stop")):
        add(env, action=act, vmid=120 + i)
    assert {r["status"] for r in run()} == {"ok"}
    assert sorted(c[1] for c in posts()) == ["/nodes/enzo/qemu/120/status/shutdown", "/nodes/enzo/qemu/121/status/reboot", "/nodes/enzo/qemu/122/status/stop"]


def test_snapshot_gets_a_valid_unique_name(env):
    sid = add(env, action="snapshot", gtype="lxc", vmid=130)
    assert run()[0] == {"id": sid, "status": "ok", "detail": "snapshot kaji-20261116-0630"}
    assert posts() == [("POST", "/nodes/enzo/lxc/130/snapshot", "snapname=kaji-20261116-0630")]


def test_protected_machines_are_refused_at_execution(env, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "kaji_protected_vmids", "115,116")
    sid = add(env)
    assert run() == [{"id": sid, "status": "refused", "detail": "machine protégée"}] and not CALLS


def test_templates_are_refused(env):
    ST["template"] = True; ST["state"] = "stopped"
    sid = add(env)
    assert run()[0] == {"id": sid, "status": "refused", "detail": "machine modèle"} and not posts()


def test_unknown_action_is_refused_even_if_the_database_says_so(env):
    sid = add(env, action="delete")
    assert run()[0]["status"] == "refused" and not CALLS and row(sid)[0] == "refused"


def test_a_failing_schedule_does_not_stop_the_others_and_leaks_nothing(env, client):
    a = add(env, vmid=115); b = add(env, vmid=116)
    ST["fail"] = True
    out = run()
    assert [r["status"] for r in out] == ["error", "error"] and {r["id"] for r in out} == {a, b}
    assert SECRET not in str(out) and SECRET not in client.get("/api/audit").text and SECRET not in str(row(a))


def test_broken_rows_are_ignored(env):
    add(env, timezone="Mars/Base"); add(env, days="x"); ok = add(env, vmid=117)
    ST["state"] = "stopped"
    assert [r["id"] for r in run()] == [ok]


def test_time_zone_matters(env):
    sid = add(env, timezone="UTC")                                              # 07:30 UTC n'est pas 06:30 UTC
    assert run() == [] and run(datetime(2026, 11, 16, 7, 30, tzinfo=timezone.utc))[0]["id"] == sid


def test_the_loop_runs_the_engine_survives_errors_and_stops_when_cancelled(env, monkeypatch):
    import app.scheduler as sch
    calls = {"n": 0}

    async def fake_run_due(db, factory, now=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boum")                                          # une erreur ne tue pas la boucle

    monkeypatch.setattr(sch, "run_due", fake_run_due)

    async def go():
        task = asyncio.create_task(sch.loop(factory, lambda: Session(get_engine()), interval=0.01))
        await asyncio.sleep(0.15)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(go())
    assert calls["n"] >= 3


def test_the_loop_also_evaluates_alerts_and_an_alert_error_does_not_stop_scheduling(env, monkeypatch):
    import app.alerts as al
    import app.scheduler as sch
    seen = {"alerts": 0, "due": 0}

    async def fake_evaluate(db, factory_, now=None, notifier=None):
        seen["alerts"] += 1
        raise RuntimeError("boum")

    async def fake_run_due(db, factory_, now=None):
        seen["due"] += 1

    monkeypatch.setattr(al, "evaluate", fake_evaluate)
    monkeypatch.setattr(sch, "run_due", fake_run_due)

    async def go():
        task = asyncio.create_task(sch.loop(factory, lambda: Session(get_engine()), interval=0.01, alerts_every=0.03))
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(go())
    assert seen["alerts"] >= 2 and seen["due"] >= seen["alerts"]                        # les alertes tournent moins souvent que le planificateur, et leur erreur ne l'arrête pas


def test_the_scheduler_is_off_during_tests(client):
    from app.config import get_settings
    assert get_settings().kaji_scheduler is False


def test_a_task_that_fails_at_proxmox_is_an_error_not_an_ok(env, client):
    """Constaté en réel : Proxmox accepte la demande puis la tâche échoue (VM d'essai : « NUMA needs to be enabled for memory hotplug »)."""
    sid = add(env)
    ST["task"] = "failed"
    out = run()
    assert out[0]["status"] == "error" and "NUMA needs to be enabled" in out[0]["detail"] and row(sid)[0] == "error"
    assert ("schedule-start", "error") in {(a["action"], a["status"]) for a in client.get("/api/audit").json()}


def test_task_outcomes_ok_warnings_empty_unreadable_and_slow(env):
    expect = {"ok": ("ok", "start"), "warn": ("ok", "start"), "empty": ("error", "état inconnu"), "unreadable": ("ok", "tâche non suivie")}
    for i, (mode, (status, text)) in enumerate(expect.items()):
        ST.clear(); ST["task"] = mode
        add(env, vmid=130 + i, time=f"07:{30 + i}")
        out = run(datetime(2026, 11, 16, 6, 30 + i, tzinfo=timezone.utc))
        assert out[-1]["status"] == status and text in out[-1]["detail"], (mode, out)
    ST.clear(); ST["task"] = "running"
    add(env, vmid=140, time="07:40")
    out = run(datetime(2026, 11, 16, 6, 40, tzinfo=timezone.utc))
    assert out[-1]["status"] == "ok" and "demandée" in out[-1]["detail"] and ST["polls"] >= 3             # suivie jusqu'au délai, sans bloquer plus


def test_a_slow_task_is_followed_until_it_finishes(env):
    sid = add(env)
    ST["task"] = "running-then-ok"
    out = run()
    assert out[0] == {"id": sid, "status": "ok", "detail": "start"} and ST["polls"] == 3


def test_snapshot_task_is_followed_too(env):
    add(env, action="snapshot", gtype="lxc", vmid=130)
    ST["task"] = "failed"
    assert run()[0]["status"] == "error"


def test_the_slot_is_remembered_before_acting(env):
    """Même si l'action plante, la minute est mémorisée : pas de rejeu au tour suivant."""
    sid = add(env)
    ST["fail"] = True
    run()
    assert row(sid)[2] == "2026-11-16 07:30" and run() == []
