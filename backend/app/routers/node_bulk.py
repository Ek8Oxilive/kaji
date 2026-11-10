"""Actions groupées d'un nœud (tout démarrer / arrêter / migrer, droits `VM.PowerMgmt` et `VM.Migrate`) et Wake-on-LAN (`Sys.PowerMgmt`).
Garde-fous dans `bulkspec` : liste de machines explicite, protégées refusées, confirmation et nom du nœud retapé ; aperçu `dry_run` sans écriture."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit
from ..bulkspec import ACTIONS, MAX_VMS, plan, proxmox_params, verdict, wake_verdict
from ..config import get_settings
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px, shape_guests, shape_status

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["node-bulk"], dependencies=[Depends(current_user)])


class BulkBody(BaseModel):
    action: Literal["startall", "stopall", "migrateall"]
    vmids: list[int] = Field(min_length=1, max_length=MAX_VMS, description="Liste explicite : Kaji n'envoie jamais « toutes les machines »")
    target: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$", description="Nœud cible (migrateall)")
    force_stop: bool = Field(default=False, description="stopall : arrêt forcé après le délai")
    timeout: int = Field(default=180, ge=10, le=7200, description="stopall : délai avant l'arrêt forcé (secondes)")
    with_local_disks: bool = False
    max_workers: int = Field(default=1, ge=1, le=8)
    confirm: bool = False
    type_name: str | None = Field(default=None, max_length=80, description="Nom exact du nœud, retapé (arrêt et migration)")
    accept_running: bool = False
    dry_run: bool = False


class WakeBody(BaseModel):
    confirm: bool = False
    type_name: str | None = Field(default=None, max_length=80)


async def _state(db, factory, conn_id: int):
    cluster = shape_status(await _px(db, factory, conn_id, "get", "/cluster/status"))
    guests = shape_guests(await _px(db, factory, conn_id, "get", "/cluster/resources", type="vm"))
    return cluster, guests


@router.post("/nodes/{node}/bulk")
async def bulk(body: BulkBody, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
               factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """`dry_run` : le plan (machines concernées, ignorées, protégées, verrous) sans rien écrire. Sinon, lance l'action et renvoie la tâche Proxmox."""
    assert body.action in ACTIONS
    act, target = f"node-{body.action}", f"node/{node}"

    def fail(code: int, msg: str):
        audit.record(db, username=user.username, connection_id=conn_id, action=act, target=target, status="error", detail=msg)
        raise HTTPException(code, msg)

    try:
        cluster, guests = await _state(db, factory, conn_id)
    except HTTPException as e:
        fail(502 if e.status_code < 500 else e.status_code, "État du cluster illisible : action refusée par précaution")
    p = plan(body.action, node, list(dict.fromkeys(body.vmids)), guests, get_settings().protected_vmids, cluster, body.target)
    if body.dry_run:
        refused = verdict(p, True, node, True)
        return {**p, "dry_run": True, "blocked": refused[1] if refused else None, "needs_accept_running": body.action == "migrateall" and bool(p["running"])}
    refused = verdict(p, body.confirm, body.type_name, body.accept_running)
    if refused:
        fail(*refused)
    try:
        upid = await _px(db, factory, conn_id, "post", f"/nodes/{node}/{body.action}",
                         **proxmox_params(p, body.force_stop, body.timeout, body.with_local_disks, body.max_workers))
    except HTTPException as e:
        fail(e.status_code, str(e.detail))
    audit.record(db, username=user.username, connection_id=conn_id, action=act, target=target, status="started",
                 detail=f"{len(p['apply'])} machine(s)" + (f" vers {body.target}" if body.action == "migrateall" else ""))
    return {"node": node, "action": body.action, "upid": upid if isinstance(upid, str) else None, "vmids": [g["vmid"] for g in p["apply"]]}


@router.post("/nodes/{node}/wakeonlan", status_code=status.HTTP_202_ACCEPTED)
async def wake(body: WakeBody, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
               factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Réveille un nœud HORS ligne par Wake-on-LAN (l'adresse MAC doit être déclarée dans la configuration du nœud chez Proxmox)."""
    act, target = "node-wakeonlan", f"node/{node}"

    def fail(code: int, msg: str):
        audit.record(db, username=user.username, connection_id=conn_id, action=act, target=target, status="error", detail=msg)
        raise HTTPException(code, msg)

    try:
        cluster = shape_status(await _px(db, factory, conn_id, "get", "/cluster/status"))
    except HTTPException as e:
        fail(502 if e.status_code < 500 else e.status_code, "État du cluster illisible : action refusée par précaution")
    me = next((n for n in cluster.get("nodes") or [] if n.get("name") == node), None)
    refused = wake_verdict(me is not None, bool(me and me.get("online")), body.confirm, body.type_name, node)
    if refused:
        fail(*refused)
    try:
        await _px(db, factory, conn_id, "post", f"/nodes/{node}/wakeonlan")
    except HTTPException as e:
        fail(e.status_code, str(e.detail))
    audit.record(db, username=user.username, connection_id=conn_id, action=act, target=target, status="started", detail="paquet envoyé")
    return {"node": node, "action": "wakeonlan"}
