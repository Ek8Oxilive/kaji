"""Notes d'une machine (droit `VM.Config.Options`) ou d'un nœud (droit `Sys.Modify`). Remplacent `description` ; rien d'autre n'est touché."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..notespec import NotesBody, shape_notes, write_params
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["notes"], dependencies=[Depends(current_user)])
GUEST = "/guests/{node}/{gtype}/{vmid}/notes"


async def _read(db, factory, conn_id, path):
    return shape_notes(await _px(db, factory, conn_id, "get", path))


async def _write(db, factory, user, conn_id, action, target, path, body: NotesBody):
    cur = await _read(db, factory, conn_id, path)
    refused = None
    if cur["digest"] is None:
        # Pas de digest : seule une configuration VIDE peut s'écrire sans (nœud sans réglage) ; toute autre est illisible, donc refusée.
        if not cur["empty"]:
            refused = (502, "Configuration illisible : modification refusée par précaution")
        elif body.digest is not None:
            refused = (409, "Les notes ont changé entre-temps : recharge et recommence")
        elif not body.notes.strip():
            return {"ok": True}                                     # rien à supprimer dans une configuration vide
    elif body.digest is None:
        refused = (400, "Le digest lu avec les notes est obligatoire")
    elif cur["digest"] != body.digest:
        refused = (409, "Les notes ont changé entre-temps : recharge et recommence")
    if refused:
        audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target, status="error", detail=refused[1])
        raise HTTPException(*refused)
    try:
        await _px(db, factory, conn_id, "put", path, **write_params(body))
    except HTTPException as e:
        audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target, status="error", detail=str(e.detail))
        raise
    audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target, status="ok", detail=f"{len(body.notes)} caractère(s)")
    return {"ok": True}


@router.get(GUEST)
async def guest_notes(conn_id: int, node: str = Path(pattern=NODE), gtype: Literal["qemu", "lxc"] = Path(), vmid: int = Path(ge=100, le=999999999),
                      db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    return await _read(db, factory, conn_id, f"/nodes/{node}/{gtype}/{vmid}/config")


@router.put(GUEST)
async def set_guest_notes(body: NotesBody, conn_id: int, node: str = Path(pattern=NODE), gtype: Literal["qemu", "lxc"] = Path(),
                          vmid: int = Path(ge=100, le=999999999), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                          user: AdminUser = Depends(current_user)):
    return await _write(db, factory, user, conn_id, "guest-notes", f"{gtype}/{vmid}@{node}", f"/nodes/{node}/{gtype}/{vmid}/config", body)


@router.get("/nodes/{node}/notes")
async def node_notes(conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    return await _read(db, factory, conn_id, f"/nodes/{node}/config")


@router.put("/nodes/{node}/notes")
async def set_node_notes(body: NotesBody, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
                         factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _write(db, factory, user, conn_id, "node-notes", f"node/{node}", f"/nodes/{node}/config", body)
