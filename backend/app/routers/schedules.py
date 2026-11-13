"""Actions planifiées (lot #411) : lister, créer, modifier, supprimer. L'exécution est dans `app/scheduler.py`.

Lecture : tout utilisateur de Kaji. Écriture : **administrateurs seulement** (`app/roles.py`, toute écriture non déclarée leur est réservée). Garde-fous : action de la liste blanche,
machine protégée refusée, machine relue chez Proxmox (elle doit exister), `stop` (arrêt forcé) exige `confirm`, 200 planifications au plus par connexion, fuseau horaire connu.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import StrictBool
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser, ScheduledAction
from ..schedulespec import MAX_PER_CONNECTION, ScheduleBody, days_to_text, next_run, parse_days, text_to_days, valid_timezone
from .auth import current_user
from .cluster import Factory, _px
from .connections import _get_or_404

router = APIRouter(prefix="/api/connections/{conn_id}/schedules", tags=["schedules"])


def _out(s: ScheduledAction) -> dict:
    try:
        nxt = next_run(text_to_days(s.days), s.time, s.timezone, datetime.now(timezone.utc)) if s.enabled else None
    except Exception:
        nxt = None
    return {"id": s.id, "node": s.node, "gtype": s.gtype, "vmid": s.vmid, "action": s.action, "days": text_to_days(s.days), "time": s.time, "timezone": s.timezone,
            "enabled": bool(s.enabled), "created_by": s.created_by, "next_run": nxt.isoformat() if nxt else None,
            "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None, "last_status": s.last_status, "last_detail": s.last_detail}


def _log(db, user, conn_id, action, target, st, detail=None):
    audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target, status=st, detail=detail)


async def _checked(db: Session, factory: Factory, user: AdminUser, conn_id: int, body: ScheduleBody, action: str) -> list[int]:
    target = f"{body.gtype}/{body.vmid}@{body.node}"

    def refuse(msg: str, code: int):
        _log(db, user, conn_id, action, target, "error", msg)
        raise HTTPException(code, msg)

    days = parse_days(list(body.days))
    if days is None:
        refuse("Jours invalides (0 = lundi à 6 = dimanche, sans doublon)", status.HTTP_422_UNPROCESSABLE_CONTENT)
    if not valid_timezone(body.timezone):
        refuse("Fuseau horaire inconnu (ex. Europe/Paris, UTC)", status.HTTP_422_UNPROCESSABLE_CONTENT)
    if body.vmid in get_settings().protected_vmids:
        refuse("Machine protégée : aucune action planifiée dessus", status.HTTP_403_FORBIDDEN)
    if body.action == "stop" and not body.confirm:
        refuse("Arrêt forcé planifié : renvoie la requête avec confirm=true (coupure sans arrêt propre, chaque semaine)", status.HTTP_400_BAD_REQUEST)
    try:
        current = await _px(db, factory, conn_id, "get", f"/nodes/{body.node}/{body.gtype}/{body.vmid}/status/current")
    except HTTPException:
        refuse("Machine introuvable ou illisible chez Proxmox", status.HTTP_422_UNPROCESSABLE_CONTENT)
    if isinstance(current, dict) and str(current.get("template")) == "1":
        refuse("Une machine modèle ne se planifie pas", status.HTTP_409_CONFLICT)
    return days


@router.get("")
def list_schedules(conn_id: int, db: Session = Depends(get_db), _u: AdminUser = Depends(current_user)):
    _get_or_404(db, conn_id)
    return [_out(s) for s in db.scalars(select(ScheduledAction).where(ScheduledAction.conn_id == conn_id).order_by(ScheduledAction.id))]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_schedule(body: ScheduleBody, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    _get_or_404(db, conn_id)
    if (db.scalar(select(func.count()).select_from(ScheduledAction).where(ScheduledAction.conn_id == conn_id)) or 0) >= MAX_PER_CONNECTION:
        _log(db, user, conn_id, "schedule-create", f"{body.gtype}/{body.vmid}@{body.node}", "error", "trop de planifications")
        raise HTTPException(status.HTTP_409_CONFLICT, f"{MAX_PER_CONNECTION} planifications au plus par connexion")
    days = await _checked(db, factory, user, conn_id, body, "schedule-create")
    s = ScheduledAction(conn_id=conn_id, node=body.node, gtype=body.gtype, vmid=body.vmid, action=body.action, days=days_to_text(days), time=body.time,
                        timezone=body.timezone, enabled=body.enabled, created_by=user.username)
    db.add(s)
    db.commit()
    _log(db, user, conn_id, "schedule-create", f"{s.gtype}/{s.vmid}@{s.node}", "started", f"#{s.id} {s.action} {s.time} jours {s.days} {s.timezone}")
    return _out(s)


@router.put("/{sid}")
async def update_schedule(body: ScheduleBody, conn_id: int, sid: int = Path(ge=1), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                          user: AdminUser = Depends(current_user)):
    s = db.get(ScheduledAction, sid)
    if s is None or s.conn_id != conn_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Planification inconnue")
    days = await _checked(db, factory, user, conn_id, body, "schedule-update")
    s.node, s.gtype, s.vmid, s.action, s.days, s.time, s.timezone, s.enabled = body.node, body.gtype, body.vmid, body.action, days_to_text(days), body.time, body.timezone, body.enabled
    s.last_key = None
    db.commit()
    _log(db, user, conn_id, "schedule-update", f"{s.gtype}/{s.vmid}@{s.node}", "started", f"#{s.id} {s.action} {s.time} jours {s.days} {s.timezone}{'' if s.enabled else ' (désactivée)'}")
    return _out(s)


@router.delete("/{sid}")
def delete_schedule(conn_id: int, sid: int = Path(ge=1), confirm: StrictBool = Query(default=False), db: Session = Depends(get_db), user: AdminUser = Depends(current_user)):
    s = db.get(ScheduledAction, sid)
    if s is None or s.conn_id != conn_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Planification inconnue")
    target = f"{s.gtype}/{s.vmid}@{s.node}"
    if not confirm:
        _log(db, user, conn_id, "schedule-delete", target, "error", "sans confirm")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Suppression : renvoie la requête avec confirm=true")
    db.delete(s)
    db.commit()
    _log(db, user, conn_id, "schedule-delete", target, "started", f"#{sid} supprimée")
    return {"deleted": sid}
