"""Clonage d'une VM ou d'un LXC (complet, ou lié à partir d'un modèle)."""
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..vmspec import POOL, STORAGE
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px
from .snapshots import SNAPNAME

router = APIRouter(tags=["clone"], dependencies=[Depends(current_user)])
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-.]{0,62}$")


class CloneBody(BaseModel):
    name: str = Field(description="Nom de la nouvelle VM (hostname pour un LXC)")
    newid: int | None = Field(default=None, ge=100, le=999999999, description="Identifiant ; libre automatiquement si absent")
    full: bool = Field(default=True, description="Clone complet (copie des disques). Un clone lié exige un modèle.")
    target_node: str | None = Field(default=None, description="Nœud de destination (par défaut : celui de la source)")
    storage: str | None = Field(default=None, description="Stockage de destination (clone complet)")
    pool: str | None = None
    snapshot: str | None = Field(default=None, description="Cloner l'état d'un snapshot")
    description: str = Field(default="", max_length=200)

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        if not NAME.fullmatch(v):
            raise ValueError("Nom invalide (lettres, chiffres, - et ., sans espace)")
        return v

    @field_validator("target_node")
    @classmethod
    def _node(cls, v):
        if v is not None and not re.fullmatch(NODE, v):
            raise ValueError("Nom de nœud invalide")
        return v

    @field_validator("storage")
    @classmethod
    def _storage(cls, v):
        if v is not None and not STORAGE.fullmatch(v):
            raise ValueError("Nom de stockage invalide")
        return v

    @field_validator("pool")
    @classmethod
    def _pool(cls, v):
        if v is not None and not POOL.fullmatch(v):
            raise ValueError("Nom de pool invalide")
        return v

    @field_validator("snapshot")
    @classmethod
    def _snap(cls, v):
        if v is not None and not re.fullmatch(SNAPNAME, v):
            raise ValueError("Nom de snapshot invalide")
        return v


def clone_params(body: CloneBody, gtype: str, newid: int) -> dict:
    p: dict = {"newid": newid, ("hostname" if gtype == "lxc" else "name"): body.name, "full": 1 if body.full else 0}
    if body.target_node:
        p["target"] = body.target_node
    if body.storage:
        if not body.full:
            raise ValueError("Le stockage de destination ne s'applique qu'à un clone complet")
        p["storage"] = body.storage
    if body.pool:
        p["pool"] = body.pool
    if body.snapshot:
        p["snapname"] = body.snapshot
    if body.description.strip():
        p["description"] = body.description.strip()
    return p


@router.post("/api/connections/{conn_id}/guests/{node}/{gtype}/{vmid}/clone", status_code=status.HTTP_202_ACCEPTED)
async def clone_guest(body: CloneBody, conn_id: int, node: str = Path(pattern=NODE), gtype: Literal["qemu", "lxc"] = Path(),
                      vmid: int = Path(ge=100, le=999999999), db: Session = Depends(get_db),
                      factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Clone une machine. Renvoie l'UPID de la tâche et l'identifiant de la copie."""
    target = f"{gtype}/{vmid}@{node}"

    def log(st, detail=None, upid=None):
        audit.record(db, username=user.username, connection_id=conn_id, action="clone", target=target, status=st, detail=detail, upid=upid)

    async def px(method, path, **kw):
        try:
            return await _px(db, factory, conn_id, method, path, **kw)
        except HTTPException as e:
            log("error", str(e.detail))
            raise

    newid = body.newid if body.newid is not None else int(await px("get", "/cluster/nextid"))
    if newid == vmid:
        log("error", "L'identifiant de la copie doit différer de celui de la source")
        raise HTTPException(422, "L'identifiant de la copie doit différer de celui de la source")
    try:
        params = clone_params(body, gtype, newid)
    except ValueError as e:
        log("error", str(e))
        raise HTTPException(422, str(e))
    upid = await px("post", f"/nodes/{node}/{gtype}/{vmid}/clone", **params)
    log("started", f"-> #{newid} {body.name}" + (f" · pool {body.pool}" if body.pool else "") + (" · lié" if not body.full else ""),
        upid=upid if isinstance(upid, str) else None)
    return {"upid": upid, "node": node, "newid": newid, "target_node": body.target_node or node}
