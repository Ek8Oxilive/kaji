"""Télécharger un modèle de conteneur du catalogue officiel Proxmox (`pveam download`), lot #147.

Aucune URL : seul un nom présent dans le catalogue RELU chez Proxmox au moment de l'appel (liste blanche dynamique) est accepté, vers un stockage qui
accepte `vztmpl` (relu aussi). Un modèle déjà présent sur ce stockage : 409 sans appel d'écriture. Proxmox vérifie lui-même les sommes de contrôle.
RIEN n'a été validé en réel (lot PC B).
"""
import re

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(tags=["aplinfo"], dependencies=[Depends(current_user)])
STORAGE = re.compile(r"[A-Za-z][A-Za-z0-9._-]{0,63}")                 # pve-storage-id
TEMPLATE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,254}")           # nom de fichier du catalogue : pas de « / » ni de « .. » isolé


class TemplateDownload(BaseModel):
    storage: str
    template: str


@router.post("/api/connections/{conn_id}/nodes/{node}/aplinfo", status_code=status.HTTP_202_ACCEPTED)
async def download_template(conn_id: int, body: TemplateDownload, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
                            factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Télécharge un modèle du catalogue officiel vers un stockage `vztmpl`. Renvoie l'UPID de la tâche."""
    target = f"{node}:{body.storage}/{body.template}"[:200]

    def log(st, detail=None, upid=None):
        audit.record(db, username=user.username, connection_id=conn_id, action="template-download", target=target, status=st, detail=detail, upid=upid)

    def refuse(msg, code):
        log("error", msg)
        raise HTTPException(code, msg)

    async def px(method, path, **kw):
        try:
            return await _px(db, factory, conn_id, method, path, **kw)
        except HTTPException as e:
            log("error", str(e.detail))
            raise

    if not STORAGE.fullmatch(body.storage):
        refuse("Nom de stockage invalide", 422)
    if not TEMPLATE.fullmatch(body.template) or ".." in body.template:
        refuse("Nom de modèle invalide", 422)

    catalogue = await px("get", f"/nodes/{node}/aplinfo")
    if not isinstance(catalogue, list) or not any(isinstance(a, dict) and a.get("type") == "lxc" and a.get("template") == body.template for a in catalogue):
        refuse("Ce modèle ne figure pas dans le catalogue officiel de Proxmox", 422)
    storages = await px("get", f"/nodes/{node}/storage", content="vztmpl")
    if not isinstance(storages, list) or not any(isinstance(s, dict) and s.get("storage") == body.storage and s.get("active", 1) for s in storages):
        refuse("Ce stockage n'accepte pas les modèles de conteneur (vztmpl) ou n'est pas actif sur ce nœud", 422)
    present = await px("get", f"/nodes/{node}/storage/{body.storage}/content", content="vztmpl")
    if not isinstance(present, list):
        refuse("Contenu du stockage illisible : téléchargement refusé", 502)
    volid = f"{body.storage}:vztmpl/{body.template}"
    if any(isinstance(i, dict) and i.get("volid") == volid for i in present):
        refuse("Ce modèle est déjà présent sur ce stockage", 409)

    upid = await px("post", f"/nodes/{node}/aplinfo", storage=body.storage, template=body.template)
    log("started", f"téléchargement de « {body.template} » vers {body.storage}", upid if isinstance(upid, str) else None)
    return {"upid": upid if isinstance(upid, str) else None, "node": node, "storage": body.storage, "template": body.template}
