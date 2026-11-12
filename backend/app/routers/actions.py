"""Actions de contrôle sur les VM/LXC, suivi des tâches Proxmox et journal d'audit."""
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser, AuditLog
from ..taskstopspec import parse_upid, stop_refusal
from .auth import current_user
from .cluster import Factory, _px

ORDER = 90        # en dernier : la route générique {action} intercepterait toute route plus spécifique (voir routers/__init__.py)
router = APIRouter(tags=["actions"], dependencies=[Depends(current_user)])

NODE = r"^[A-Za-z0-9]([A-Za-z0-9\-]{0,62})$"
UPID = re.compile(r"^UPID:[A-Za-z0-9\-]+:[0-9A-Fa-f]+:[0-9A-Fa-f]+:[0-9A-Fa-f]+:[a-z0-9]+:[^:/\s]*:[^:/\s]+:$")

Action = Literal["start", "stop", "shutdown", "reboot"]
# Actions brutales : exigent confirm=true (coupure sans arrêt propre)
NEEDS_CONFIRM = {"stop"}


class ActionBody(BaseModel):
    confirm: bool = False


def _check_upid(upid: str) -> str:
    if not UPID.fullmatch(upid):
        raise HTTPException(422, "Identifiant de tâche (UPID) invalide")
    return upid


@router.post("/api/connections/{conn_id}/guests/{node}/{gtype}/{vmid}/{action}", status_code=status.HTTP_202_ACCEPTED)
async def guest_action(
    conn_id: int,
    action: Action,
    node: str = Path(pattern=NODE),
    gtype: Literal["qemu", "lxc"] = Path(),
    vmid: int = Path(ge=100, le=999999999),
    body: ActionBody | None = None,
    db: Session = Depends(get_db),
    factory: Factory = Depends(get_client_factory),
    user: AdminUser = Depends(current_user),
):
    """Démarre, arrête (brutal), éteint proprement ou redémarre une VM/LXC. Renvoie l'UPID de la tâche."""
    target = f"{gtype}/{vmid}@{node}"
    if action in NEEDS_CONFIRM and not (body and body.confirm):
        audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target,
                     status="error", detail="confirmation manquante")
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"« {action} » coupe brutalement la machine : renvoie la requête avec {{\"confirm\": true}}")
    if action == "start":
        # Un modèle ne démarre pas : refus net (409) au lieu d'une tâche qui échoue chez Proxmox (essai réel, ticket #204).
        # Config illisible : on laisse Proxmox trancher, pour ne jamais bloquer un démarrage légitime.
        # Déjà en marche : refus net (409) au lieu d'un 202 suivi d'une tâche en échec « already running » (essai réel, ticket #291).
        # Une VM en pause (`running` + `qmpstatus` paused) se reprend, elle ne se démarre pas. État illisible : Proxmox tranche.
        try:
            current = await _px(db, factory, conn_id, "get", f"/nodes/{node}/{gtype}/{vmid}/status/current")
        except HTTPException:
            current = None
        if isinstance(current, dict) and current.get("status") == "running":
            paused = str(current.get("qmpstatus")) in ("paused", "suspended")
            audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target,
                         status="error", detail="machine en pause" if paused else "machine déjà en marche")
            raise HTTPException(status.HTTP_409_CONFLICT, "La VM est en pause : reprends-la au lieu de la démarrer" if paused
                                else "La machine est déjà en marche")
        try:
            cfg = await _px(db, factory, conn_id, "get", f"/nodes/{node}/{gtype}/{vmid}/config", current=1)
        except HTTPException:
            cfg = None
        if isinstance(cfg, dict) and str(cfg.get("template")) == "1":
            audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target,
                         status="error", detail="machine modèle")
            raise HTTPException(status.HTTP_409_CONFLICT, "Une machine modèle ne démarre pas : clone-la, puis démarre la copie")
    try:
        upid = await _px(db, factory, conn_id, "post", f"/nodes/{node}/{gtype}/{vmid}/status/{action}")
    except HTTPException as e:
        audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target,
                     status="error", detail=str(e.detail))
        raise
    audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target,
                 status="started", upid=upid if isinstance(upid, str) else None)
    return {"upid": upid, "node": node, "action": action}


@router.get("/api/connections/{conn_id}/tasks/{node}/{upid}")
async def task_status(conn_id: int, upid: str, node: str = Path(pattern=NODE),
                      db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """État d'une tâche : running, ou stopped avec son exitstatus (« OK » si réussie)."""
    d = await _px(db, factory, conn_id, "get", f"/nodes/{node}/tasks/{_check_upid(upid)}/status")
    return {"status": d.get("status"), "exitstatus": d.get("exitstatus"), "type": d.get("type"),
            "id": d.get("id"), "user": d.get("user"), "starttime": d.get("starttime"),
            # « WARNINGS: n » = tâche réussie avec n avertissements (ex. « Systemd détecté, activer l'imbrication ») :
            # ce n'est pas un échec, mais l'interface doit pouvoir le signaler.
            "ok": d.get("status") == "stopped" and (d.get("exitstatus") == "OK" or str(d.get("exitstatus", "")).startswith("WARNINGS")),
            "warnings": str(d.get("exitstatus", "")).startswith("WARNINGS"),
            # Le bouton « Arrêter » n'est proposé que si le serveur accepterait l'arrêt (en cours, type autorisé, machine non protégée), ticket #310.
            "stoppable": d.get("status") == "running" and stop_refusal(parse_upid(upid), get_settings().protected_vmids) is None}


@router.get("/api/connections/{conn_id}/tasks/{node}/{upid}/log")
async def task_log(conn_id: int, upid: str, node: str = Path(pattern=NODE),
                   start: int = Query(default=0, ge=0), limit: int = Query(default=200, ge=1, le=1000),
                   db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    lines = await _px(db, factory, conn_id, "get", f"/nodes/{node}/tasks/{_check_upid(upid)}/log",
                      start=start, limit=limit)
    return [{"n": l.get("n"), "t": l.get("t")} for l in lines]


@router.get("/api/audit")
def audit_log(limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).all()
    return [{"id": r.id, "ts": r.ts.isoformat(), "user": r.username, "connection_id": r.connection_id,
             "action": r.action, "target": r.target, "status": r.status, "upid": r.upid,
             "detail": r.detail} for r in rows]
