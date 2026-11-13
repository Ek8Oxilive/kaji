"""Évaluation des alertes (lot #413). `evaluate` est testable sans boucle ni horloge ; le minuteur est dans `app/scheduler.py`.

Cycle d'une alerte à seuil, par sujet (nœud, stockage) : seuil dépassé → `pending` ; toujours dépassé après `minutes` → `firing` (notification) ; plus dépassé → `resolved` (notification),
ou supprimée si elle n'avait jamais atteint `firing`. `task_failed` : une alerte (déjà `resolved`, c'est un fait) par tâche en échec, sans jamais rejouer une tâche déjà vue.
Notification : webhook facultatif de la règle (adresse chiffrée en base, jamais journalisée ni renvoyée) ; un échec d'envoi est noté dans l'alerte, sans l'adresse.
Une connexion injoignable est ignorée (rien n'est résolu ni déclenché à tort) ; une erreur sur une règle n'arrête pas les autres.
"""
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .alertspec import THRESHOLD_KINDS, breaches, failed_tasks, read_measures
from .config import get_settings
from .crypto import decrypt
from .isospec import check_url
from .models import AlertEvent, AlertRule
from .routers.cluster import Factory, _px

log = logging.getLogger("kaji.alerts")
ACTOR = "alertes"
Notifier = Callable[[str, str, dict], Awaitable[bool]]
LABEL = {"cpu": "CPU", "mem": "RAM", "storage": "stockage", "node_offline": "nœud hors ligne", "task_failed": "tâche en échec"}


async def send_webhook(url: str, text: str, payload: dict) -> bool:
    """POST JSON `{text, kaji}` (compatible Slack / Mattermost / Teams), 5 s, sans suivre de redirection. Renvoie True si le serveur répond 2xx. Jamais d'exception."""
    try:
        check_url(url)                                          # défense en profondeur : même contrôle qu'à l'enregistrement
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as c:
            r = await c.post(url, json={"text": text, "kaji": payload})
        return 200 <= r.status_code < 300
    except Exception:
        return False


def _message(rule: AlertRule, subject: str, value: int | None, state: str) -> str:
    what = LABEL.get(rule.kind, rule.kind)
    if rule.kind in THRESHOLD_KINDS:
        base = f"{what} {value} % sur {subject} (seuil {rule.threshold} %, depuis {rule.minutes} min)"
    else:
        base = f"{what} : {subject}"
    return f"[Kaji] {'RÉSOLU' if state == 'resolved' else 'ALERTE'} {rule.name} : {base}"


async def _notify(db: Session, notifier: Notifier, rule: AlertRule, ev: AlertEvent, state: str) -> None:
    text = _message(rule, ev.subject, ev.value, state)
    audit.record(db, username=ACTOR, connection_id=rule.conn_id, action=f"alert-{state}", target=f"{rule.name}: {ev.subject}"[:200], status="started", detail=text[:200])
    if not rule.webhook_enc:
        return
    try:
        url = decrypt(get_settings().kaji_secret_key, rule.webhook_enc)
    except Exception:
        ev.detail = "adresse du webhook illisible"
        return
    ok = await notifier(url, text, {"rule": rule.name, "kind": rule.kind, "subject": ev.subject, "value": ev.value, "state": state})
    if not ok:
        ev.detail = "notification échouée"[:200]


async def _threshold_rule(db: Session, notifier: Notifier, rule: AlertRule, m: dict, now: datetime, out: list) -> None:
    current = breaches(rule.kind, rule.threshold, m)
    opened = {e.subject: e for e in db.scalars(select(AlertEvent).where(AlertEvent.rule_id == rule.id, AlertEvent.status.in_(("pending", "firing"))))}
    for subject, value in current.items():
        ev = opened.get(subject)
        if ev is None:
            ev = AlertEvent(rule_id=rule.id, conn_id=rule.conn_id, subject=subject, status="pending", since=now, value=value)
            db.add(ev)
            opened[subject] = ev
        ev.value = value
        since = ev.since if ev.since.tzinfo else ev.since.replace(tzinfo=timezone.utc)
        if ev.status == "pending" and now - since >= timedelta(minutes=rule.minutes):
            ev.status, ev.fired_at = "firing", now
            await _notify(db, notifier, rule, ev, "firing")
            out.append({"rule": rule.id, "subject": subject, "state": "firing", "value": value})
    for subject, ev in opened.items():
        if subject in current:
            continue
        if ev.status == "firing":
            ev.status, ev.resolved_at = "resolved", now
            await _notify(db, notifier, rule, ev, "resolved")
            out.append({"rule": rule.id, "subject": subject, "state": "resolved", "value": ev.value})
        else:
            db.delete(ev)                                       # jamais déclenchée : on n'en garde pas de trace
    db.commit()


async def _task_rule(db: Session, notifier: Notifier, rule: AlertRule, tasks, now: datetime, out: list) -> None:
    new = failed_tasks(tasks, rule.cursor)
    if rule.cursor == 0 and new:                                # première évaluation : on ne remonte pas l'historique, on se cale sur la fin de la dernière tâche
        rule.cursor = new[-1]["end"]
        db.commit()
        return
    for t in new[-20:]:                                         # au plus 20 alertes par passage
        subject = f"{t['type']} {t['id']}@{t['node']}".strip()[:80]
        ev = AlertEvent(rule_id=rule.id, conn_id=rule.conn_id, subject=subject, status="resolved", since=now, fired_at=now, resolved_at=now, detail=t["status"][:200])
        db.add(ev)
        await _notify(db, notifier, rule, ev, "firing")
        out.append({"rule": rule.id, "subject": subject, "state": "firing", "value": None})
    if new:
        rule.cursor = new[-1]["end"]
    db.commit()


async def evaluate(db: Session, factory: Factory, now: datetime | None = None, notifier: Notifier = send_webhook) -> list[dict]:
    """Évalue toutes les règles actives ; renvoie les changements d'état (déclenchée, résolue)."""
    now = now or datetime.now(timezone.utc)
    out: list[dict] = []
    rules = db.scalars(select(AlertRule).where(AlertRule.enabled.is_(True)).order_by(AlertRule.conn_id, AlertRule.id)).all()
    by_conn: dict[int, list[AlertRule]] = {}
    for r in rules:
        by_conn.setdefault(r.conn_id, []).append(r)
    for conn_id, group in by_conn.items():
        try:
            resources = await _px(db, factory, conn_id, "get", "/cluster/resources")
            tasks = await _px(db, factory, conn_id, "get", "/cluster/tasks") if any(r.kind == "task_failed" for r in group) else None
        except HTTPException:
            continue                                            # connexion injoignable : rien n'est déclenché ni résolu à tort
        except Exception:
            log.exception("alertes: lecture")
            continue
        m = read_measures(resources)
        for rule in group:
            try:
                if rule.kind == "task_failed":
                    await _task_rule(db, notifier, rule, tasks, now, out)
                else:
                    await _threshold_rule(db, notifier, rule, m, now, out)
            except Exception:
                db.rollback()
                log.exception("alertes: règle %s", rule.id)
    return out
