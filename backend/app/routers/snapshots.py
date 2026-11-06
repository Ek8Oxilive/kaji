"""Snapshots des VM et LXC : lister, créer, supprimer, restaurer."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(tags=["snapshots"], dependencies=[Depends(current_user)])
BASE = "/api/connections/{conn_id}/guests/{node}/{gtype}/{vmid}/snapshots"
SNAPNAME = r"^[A-Za-z][A-Za-z0-9_\-]{1,39}$"


class SnapshotCreate(BaseModel):
    name: str = Field(pattern=SNAPNAME)
    description: str = Field(default="", max_length=200)
    vmstate: bool = Field(default=False, description="Inclure la mémoire (VM en marche uniquement)")


class Confirm(BaseModel):
    confirm: bool = False


def _ctx(node: str, gtype: str, vmid: int):
    return f"/nodes/{node}/{gtype}/{vmid}/snapshot", f"{gtype}/{vmid}@{node}"


@router.get(BASE)
async def list_snapshots(conn_id: int, node: str = Path(pattern=NODE), gtype: Literal["qemu", "lxc"] = Path(),
                         vmid: int = Path(ge=100, le=999999999), db: Session = Depends(get_db),
                         factory: Factory = Depends(get_client_factory)):
    path, _ = _ctx(node, gtype, vmid)
    items = await _px(db, factory, conn_id, "get", path)
    snaps = [{"name": i["name"], "description": i.get("description", ""), "time": i.get("snaptime"),
              "vmstate": bool(i.get("vmstate")), "parent": i.get("parent")} for i in items if i.get("name") != "current"]
    cur = next((i for i in items if i.get("name") == "current"), {})
    return {"snapshots": sorted(snaps, key=lambda s: s["time"] or 0), "current_parent": cur.get("parent")}


def _guard(db, user, conn_id, action, target):
    """Journalise un refus avant tout appel Proxmox."""
    def refuse(msg: str, code: int = 400):
        audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target,
                     status="error", detail=msg)
        raise HTTPException(code, msg)
    return refuse


async def _call(db, factory, user, conn_id, action, target, method, path, detail=None, **params):
    try:
        upid = await _px(db, factory, conn_id, method, path, **params)
    except HTTPException as e:
        audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target,
                     status="error", detail=str(e.detail))
        raise
    audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target,
                 status="started", upid=upid if isinstance(upid, str) else None, detail=detail)
    return {"upid": upid, "node": node_of(path)}


def node_of(path: str) -> str:
    return path.split("/")[2]


@router.post(BASE, status_code=status.HTTP_202_ACCEPTED)
async def create_snapshot(body: SnapshotCreate, conn_id: int, node: str = Path(pattern=NODE),
                          gtype: Literal["qemu", "lxc"] = Path(), vmid: int = Path(ge=100, le=999999999),
                          db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                          user: AdminUser = Depends(current_user)):
    path, target = _ctx(node, gtype, vmid)
    if body.vmstate and gtype == "lxc":
        _guard(db, user, conn_id, "snapshot-create", target)("Un LXC n'a pas d'état mémoire à sauvegarder", 422)
    params: dict = {"snapname": body.name}
    if body.description.strip():
        params["description"] = body.description.strip()
    if body.vmstate:
        params["vmstate"] = 1
    return await _call(db, factory, user, conn_id, "snapshot-create", target, "post", path, detail=body.name, **params)


@router.delete(BASE + "/{name}", status_code=status.HTTP_202_ACCEPTED)
async def delete_snapshot(conn_id: int, name: str = Path(pattern=SNAPNAME), node: str = Path(pattern=NODE),
                          gtype: Literal["qemu", "lxc"] = Path(), vmid: int = Path(ge=100, le=999999999),
                          confirm: bool = Query(default=False), db: Session = Depends(get_db),
                          factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    path, target = _ctx(node, gtype, vmid)
    if not confirm:
        _guard(db, user, conn_id, "snapshot-delete", f"{target}:{name}")(
            "Supprimer un snapshot supprime ce point de restauration : renvoie la requête avec ?confirm=true")
    return await _call(db, factory, user, conn_id, "snapshot-delete", f"{target}:{name}", "delete", f"{path}/{name}", detail=name)


@router.post(BASE + "/{name}/rollback", status_code=status.HTTP_202_ACCEPTED)
async def rollback_snapshot(body: Confirm, conn_id: int, name: str = Path(pattern=SNAPNAME),
                            node: str = Path(pattern=NODE), gtype: Literal["qemu", "lxc"] = Path(),
                            vmid: int = Path(ge=100, le=999999999), db: Session = Depends(get_db),
                            factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Restaure la machine à l'état du snapshot. Tout ce qui a changé depuis est perdu."""
    path, target = _ctx(node, gtype, vmid)
    if not body.confirm:
        _guard(db, user, conn_id, "snapshot-rollback", f"{target}:{name}")(
            "La restauration écrase l'état actuel de la machine : renvoie la requête avec {\"confirm\": true}")
    return await _call(db, factory, user, conn_id, "snapshot-rollback", f"{target}:{name}", "post", f"{path}/{name}/rollback", detail=name)
