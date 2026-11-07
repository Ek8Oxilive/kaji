"""Redémarrer / éteindre un nœud (droit `Sys.PowerMgmt`). Garde-fous dans `powerspec` ; évaluation lisible avant d'agir."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..powerspec import assess, verdict
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px, shape_guests, shape_status

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["node-power"], dependencies=[Depends(current_user)])


class PowerBody(BaseModel):
    action: Literal["reboot", "shutdown"]
    confirm: bool = False
    type_name: str | None = Field(default=None, max_length=80, description="Nom exact du nœud, retapé")
    accept_guests: bool = False
    accept_quorum_loss: bool = False


async def _assessment(db, factory, conn_id: int, node: str) -> dict:
    cluster = shape_status(await _px(db, factory, conn_id, "get", "/cluster/status"))
    guests = shape_guests(await _px(db, factory, conn_id, "get", "/cluster/resources", type="vm"))
    return assess(node, cluster, guests, get_settings().protected_vmids)


@router.get("/nodes/{node}/power")
async def power_check(conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Conséquences d'un redémarrage ou d'un arrêt : machines en marche, machines protégées, perte de quorum. Lecture seule."""
    return await _assessment(db, factory, conn_id, node)


@router.post("/nodes/{node}/power", status_code=status.HTTP_202_ACCEPTED)
async def power(body: PowerBody, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
                factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    act, target = f"node-{body.action}", f"node/{node}"

    def fail(code: int, msg: str):
        audit.record(db, username=user.username, connection_id=conn_id, action=act, target=target, status="error", detail=msg)
        raise HTTPException(code, msg)

    try:
        a = await _assessment(db, factory, conn_id, node)
    except HTTPException as e:
        fail(502 if e.status_code < 500 else e.status_code, "État du cluster illisible : action refusée par précaution")
    refused = verdict(body.action, node, body.confirm, body.type_name, body.accept_guests, body.accept_quorum_loss, a)
    if refused:
        fail(*refused)
    try:
        await _px(db, factory, conn_id, "post", f"/nodes/{node}/status", command=body.action)
    except HTTPException as e:
        fail(e.status_code, str(e.detail))
    audit.record(db, username=user.username, connection_id=conn_id, action=act, target=target, status="started",
                 detail=f"{len(a['running_guests'])} machine(s) en marche")
    return {"node": node, "action": body.action}
