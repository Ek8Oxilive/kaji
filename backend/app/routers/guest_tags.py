"""Étiquettes d'une VM ou d'un conteneur (droit `VM.Config.Options`). Remplace l'ensemble ; ne touche à aucune autre option."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..tagspec import TagsBody
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["guest-tags"], dependencies=[Depends(current_user)])


@router.put("/guests/{node}/{gtype}/{vmid}/tags")
async def set_tags(body: TagsBody, conn_id: int, node: str = Path(pattern=NODE), gtype: Literal["qemu", "lxc"] = Path(),
                   vmid: int = Path(ge=100, le=999999999), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                   user: AdminUser = Depends(current_user)):
    """Remplace les étiquettes de la machine (liste vide : toutes retirées)."""
    target = f"{gtype}/{vmid}@{node}"
    params = {"tags": ";".join(body.tags)} if body.tags else {"delete": "tags"}
    try:
        await _px(db, factory, conn_id, "put", f"/nodes/{node}/{gtype}/{vmid}/config", **params)
    except HTTPException as e:
        audit.record(db, username=user.username, connection_id=conn_id, action="guest-tags", target=target, status="error", detail=str(e.detail))
        raise
    audit.record(db, username=user.username, connection_id=conn_id, action="guest-tags", target=target, status="ok", detail=f"{len(body.tags)} étiquette(s)")
    return {"tags": body.tags}
