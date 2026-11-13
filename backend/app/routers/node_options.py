"""Options d'un nœud (Nœud → Système → Options) : réveil à distance, délai de démarrage, ballooning. Lot #403.

Lecture : droit `Sys.Audit`. Écriture : `Sys.Modify` sur `/`, `digest` lu juste avant exigé, `confirm=true`, `dry_run`, relecture après l'écriture, audit.
Seules les options demandées sont envoyées ; les notes (`description`) et l'ACME ne sont jamais touchés.
"""
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..nodeoptspec import OptionsBody, build_params, shape_options
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}/nodes/{node}/options", tags=["node-options"], dependencies=[Depends(current_user)])


@router.get("")
async def node_options(conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    return shape_options(await _px(db, factory, conn_id, "get", f"/nodes/{node}/config"))


@router.put("")
async def set_node_options(body: OptionsBody, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                           user: AdminUser = Depends(current_user)):
    target = f"node/{node}"

    def refuse(msg: str, code: int):
        audit.record(db, username=user.username, connection_id=conn_id, action="node-options", target=target, status="error", detail=msg)
        raise HTTPException(code, msg)

    path = f"/nodes/{node}/config"
    cur = shape_options(await _px(db, factory, conn_id, "get", path))
    try:
        params = build_params(cur, body)
    except ValueError as e:
        refuse(str(e), status.HTTP_422_UNPROCESSABLE_ENTITY)
    if cur["digest"] is None and not cur["empty"]:
        refuse("Configuration du nœud illisible : modification refusée par précaution", status.HTTP_502_BAD_GATEWAY)
    if cur["digest"] is not None and body.digest is None:
        refuse("Le digest lu avec les options est obligatoire", status.HTTP_400_BAD_REQUEST)
    if cur["digest"] != body.digest:
        refuse("Les options du nœud ont changé entre-temps : recharge et recommence", status.HTTP_409_CONFLICT)
    if body.dry_run:
        return {"dry_run": True, "params": params}
    if not body.confirm:
        refuse("Écriture des options du nœud : renvoie la requête avec confirm=true", status.HTTP_400_BAD_REQUEST)
    try:
        await _px(db, factory, conn_id, "put", path, **params, **({"digest": body.digest} if body.digest else {}))
    except HTTPException as e:
        refuse(str(e.detail), e.status_code)
    now = shape_options(await _px(db, factory, conn_id, "get", path))
    wol = now["wakeonlan"] or {}
    expected_ok = ((body.wakeonlan_mac is None or wol.get("mac") == body.wakeonlan_mac)
                   and (body.wakeonlan_bind_interface is None or wol.get("bind_interface") == body.wakeonlan_bind_interface)
                   and (body.wakeonlan_broadcast_address is None or wol.get("broadcast_address") == body.wakeonlan_broadcast_address)
                   and (body.startall_onboot_delay is None or now["startall_onboot_delay"] == body.startall_onboot_delay)
                   and (body.ballooning_target is None or now["ballooning_target"] == body.ballooning_target)
                   and ("wakeonlan" not in body.clear or now["wakeonlan"] is None)
                   and ("startall-onboot-delay" not in body.clear or now["startall_onboot_delay"] is None)
                   and ("ballooning-target" not in body.clear or now["ballooning_target"] is None))
    if not expected_ok:
        refuse("Proxmox n'a pas appliqué la modification", status.HTTP_502_BAD_GATEWAY)
    audit.record(db, username=user.username, connection_id=conn_id, action="node-options", target=target, status="ok", detail=", ".join(sorted(k for k in params if k != "delete")) + (f" ; retiré : {params['delete']}" if "delete" in params else ""))
    return now
