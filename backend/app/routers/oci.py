"""Images OCI (Proxmox 9) : lister les étiquettes d'un dépôt et faire télécharger une image par le nœud dans un stockage. Lot #405.

Le nœud sort sur Internet : `confirm=true` exigé, registre local refusé, référence validée (motif de Proxmox), droits `Datastore.AllocateTemplate` sur le stockage et
`Sys.AccessNetwork` sur le nœud. Jetons acceptés (`allowtoken: 1`). Une image déjà présente est refusée par Proxmox. Aucun identifiant de registre n'est jamais géré.
"""
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field, StrictBool
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..ocispec import check_filename, check_reference, check_repository, shape_tags
from ..vmspec import STORAGE
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}/nodes/{node}", tags=["oci"], dependencies=[Depends(current_user)])


class PullBody(BaseModel):
    reference: str = Field(max_length=300)
    filename: str | None = Field(default=None, max_length=101)
    confirm: StrictBool = False


@router.get("/oci/tags")
async def oci_tags(conn_id: int, node: str = Path(pattern=NODE), reference: str = Query(max_length=300), db: Session = Depends(get_db),
                   factory: Factory = Depends(get_client_factory)):
    """Étiquettes d'un dépôt (`[registre/]dépôt`, sans étiquette) : requête faite par le nœud, rien n'est téléchargé."""
    try:
        check_repository(reference)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from None
    return {"tags": shape_tags(await _px(db, factory, conn_id, "get", f"/nodes/{node}/query-oci-repo-tags", reference=reference))}


@router.post("/storage/{storage}/oci-pull", status_code=status.HTTP_202_ACCEPTED)
async def oci_pull(body: PullBody, conn_id: int, node: str = Path(pattern=NODE), storage: str = Path(pattern=STORAGE.pattern), db: Session = Depends(get_db),
                   factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Le nœud télécharge l'image dans le stockage (tâche longue, suivie par `upid`)."""
    target = f"{storage}/{body.reference}@{node}"

    def refuse(msg: str, code: int):
        audit.record(db, username=user.username, connection_id=conn_id, action="storage-oci-pull", target=target, status="error", detail=msg)
        raise HTTPException(code, msg)

    try:
        check_reference(body.reference)
        if body.filename is not None:
            check_filename(body.filename)
    except ValueError as e:
        refuse(str(e), status.HTTP_422_UNPROCESSABLE_ENTITY)
    if not body.confirm:
        refuse("Le nœud va télécharger une image depuis un registre sur Internet : renvoie la requête avec confirm=true", status.HTTP_400_BAD_REQUEST)
    params = {"reference": body.reference, **({"filename": body.filename} if body.filename else {})}
    try:
        upid = await _px(db, factory, conn_id, "post", f"/nodes/{node}/storage/{storage}/oci-registry-pull", **params)
    except HTTPException as e:
        refuse(str(e.detail), e.status_code)
    audit.record(db, username=user.username, connection_id=conn_id, action="storage-oci-pull", target=target, status="started",
                 detail="image OCI demandée au registre" + (", nom de fichier choisi" if body.filename else ""), upid=upid if isinstance(upid, str) else None)
    return {"upid": upid, "node": node}
