"""Sauvegardes vzdump : lister, lancer une sauvegarde manuelle, supprimer une sauvegarde."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from .. import audit
from ..backupspec import BACKUP_FILE, BackupBody, _protected, shape_backups, vzdump_params
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..vmspec import STORAGE
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["backups"], dependencies=[Depends(current_user)])


@router.get("/nodes/{node}/storage/{storage}/backups")
async def list_backups(conn_id: int, node: str = Path(pattern=NODE), storage: str = Path(pattern=STORAGE.pattern),
                       vmid: int | None = Query(default=None, ge=100, le=999999999),
                       db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Sauvegardes d'un stockage (`content=backup`), de la plus récente à la plus ancienne. Lecture seule."""
    data = await _px(db, factory, conn_id, "get", f"/nodes/{node}/storage/{storage}/content", content="backup")
    return shape_backups(data, vmid)


@router.post("/nodes/{node}/backups")
async def create_backup(conn_id: int, body: BackupBody, node: str = Path(pattern=NODE),
                        db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                        user: AdminUser = Depends(current_user)):
    """Lance une sauvegarde manuelle d'une VM ou d'un conteneur et renvoie l'UPID de la tâche. Ne supprime rien."""
    target = f"{body.vmid}@{node}"
    detail = f"stockage={body.storage} mode={body.mode} compression={body.compress}" + \
             (" notes=définies" if body.notes else "")
    try:
        upid = await _px(db, factory, conn_id, "post", f"/nodes/{node}/vzdump", **vzdump_params(body))
    except HTTPException as e:
        audit.record(db, username=user.username, connection_id=conn_id, action="backup-create", target=target,
                     status="error", detail=f"{detail} · {e.detail}")
        raise
    audit.record(db, username=user.username, connection_id=conn_id, action="backup-create", target=target,
                 status="started", detail=detail, upid=upid if isinstance(upid, str) else None)
    return {"upid": upid, "node": node, "vmid": body.vmid, "storage": body.storage}


@router.delete("/nodes/{node}/storage/{storage}/backups/{volume}")
async def delete_backup(conn_id: int, node: str = Path(pattern=NODE), storage: str = Path(pattern=STORAGE.pattern),
                        volume: str = Path(pattern=BACKUP_FILE.pattern), confirm: bool = Query(default=False),
                        name: str = Query(default="", max_length=200), db: Session = Depends(get_db),
                        factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Supprime DÉFINITIVEMENT une sauvegarde. Exige : confirm=true, le nom exact du fichier retapé (?name=), et une
    sauvegarde non protégée. Une seule sauvegarde à la fois, jamais de suppression en masse."""
    target = f"{storage}:backup/{volume}@{node}"

    def log(st, detail=None, upid=None):
        audit.record(db, username=user.username, connection_id=conn_id, action="backup-delete", target=target,
                     status=st, detail=detail, upid=upid)

    def refuse(msg, code):
        log("error", msg)
        raise HTTPException(code, msg)

    async def px(method, path, **kw):
        try:
            return await _px(db, factory, conn_id, method, path, **kw)
        except HTTPException as e:
            log("error", str(e.detail))
            raise

    if not confirm:
        refuse("Suppression définitive : renvoie la requête avec ?confirm=true et le nom du fichier (?name=)", 400)
    if name != volume:
        refuse("Le nom du fichier ne correspond pas : suppression refusée", 400)

    volid = f"{storage}:backup/{volume}"
    listing = await px("get", f"/nodes/{node}/storage/{storage}/content", content="backup")
    found = next((v for v in listing if isinstance(v, dict) and v.get("volid") == volid), None) \
        if isinstance(listing, list) else None
    if found is None:
        refuse("Sauvegarde introuvable sur ce stockage", 404)
    if found.get("content") not in (None, "backup"):
        refuse("Ce volume n'est pas une sauvegarde : suppression refusée", 409)
    if _protected(found.get("protected")):
        refuse("Sauvegarde protégée dans Proxmox : retire d'abord la protection", 409)

    upid = await px("delete", f"/nodes/{node}/storage/{storage}/content/{quote(volid, safe='')}")
    log("started", f"sauvegarde SUPPRIMÉE : {volid}", upid=upid if isinstance(upid, str) else None)
    return {"upid": upid if isinstance(upid, str) else None, "deleted": volid}
