"""Exécution des actions planifiées (lot #411). `run_due` est testable sans horloge ni boucle ; `loop` n'est qu'un minuteur.

Garde-fous : action de la liste blanche seulement ; machines de `KAJI_PROTECTED_VMIDS` refusées (aussi à l'exécution) ; l'état de la machine est relu avant d'agir
(démarrer une machine déjà en marche, arrêter une machine arrêtée : ignoré, pas d'erreur) ; un créneau n'est JAMAIS rejoué ni rattrapé (la minute est mémorisée AVANT l'action) ;
une erreur d'une planification n'empêche pas les autres ; chaque exécution est auditée (utilisateur « planificateur »).
"""
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .config import get_settings
from .models import ScheduledAction
from .routers.cluster import Factory, _px
from .schedulespec import ACTIONS, is_due, text_to_days

log = logging.getLogger("kaji.scheduler")
ACTOR = "planificateur"
POWER = {"start", "shutdown", "reboot", "stop"}


def _target(s: ScheduledAction) -> str:
    return f"{s.gtype}/{s.vmid}@{s.node}"


async def _execute(db: Session, factory: Factory, s: ScheduledAction, now_utc: datetime) -> tuple[str, str]:
    """`(statut, détail)` : ok, skipped, refused, error."""
    if s.action not in ACTIONS:
        return "refused", "action inconnue"
    if s.vmid in get_settings().protected_vmids:
        return "refused", "machine protégée"
    base = f"/nodes/{s.node}/{s.gtype}/{s.vmid}"
    try:
        if s.action == "snapshot":
            name = "kaji-" + now_utc.strftime("%Y%m%d-%H%M")
            await _px(db, factory, s.conn_id, "post", f"{base}/snapshot", snapname=name)
            return "ok", f"snapshot {name}"
        current = await _px(db, factory, s.conn_id, "get", f"{base}/status/current")
        running = isinstance(current, dict) and current.get("status") == "running"
        if s.action == "start" and running:
            return "skipped", "déjà en marche"
        if s.action != "start" and isinstance(current, dict) and current.get("status") == "stopped":
            return "skipped", "déjà arrêtée"
        if isinstance(current, dict) and str(current.get("template")) == "1":
            return "refused", "machine modèle"
        await _px(db, factory, s.conn_id, "post", f"{base}/status/{s.action}")
        return "ok", s.action
    except HTTPException as e:
        return "error", str(e.detail)[:180]


async def run_due(db: Session, factory: Factory, now_utc: datetime | None = None) -> list[dict]:
    """Exécute les planifications dues à `now_utc` ; renvoie un résumé par planification exécutée."""
    now_utc = now_utc or datetime.now(timezone.utc)
    done: list[dict] = []
    for s in db.scalars(select(ScheduledAction).where(ScheduledAction.enabled.is_(True)).order_by(ScheduledAction.id)).all():
        try:
            due, key = is_due(text_to_days(s.days), s.time, s.timezone, now_utc, s.last_key)
        except Exception:                                       # fuseau illisible, ligne abîmée : ignorée, jamais fatale
            continue
        if not due:
            continue
        s.last_key = key                                        # mémorisé AVANT d'agir : un plantage ne rejoue pas l'action
        db.commit()
        status, detail = await _execute(db, factory, s, now_utc)
        s.last_run_at, s.last_status, s.last_detail = now_utc, status, detail[:200]
        db.commit()
        audit.record(db, username=ACTOR, connection_id=s.conn_id, action=f"schedule-{s.action}", target=_target(s),
                     status="started" if status in ("ok", "skipped") else "error", detail=f"#{s.id} {status} : {detail}"[:200])
        done.append({"id": s.id, "status": status, "detail": detail})
    return done


async def loop(factory: Factory, session_factory, interval: float = 20.0) -> None:
    """Réveille le planificateur toutes les `interval` secondes (la minute est dédoublonnée par `last_key`)."""
    while True:
        try:
            with session_factory() as db:
                await run_due(db, factory)
        except asyncio.CancelledError:
            raise
        except Exception:                                       # jamais de plantage de la boucle
            log.exception("planificateur")
        await asyncio.sleep(interval)
