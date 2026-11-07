"""Services d'un nœud : démarrer, arrêter, redémarrer, recharger (droit `Sys.Modify`). Garde-fous dans `servicespec`."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..servicespec import verdict
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["node-services"], dependencies=[Depends(current_user)])


class ServiceAction(BaseModel):
    confirm: bool = False
    type_name: str | None = Field(default=None, max_length=80, description="Nom du service retapé (services vitaux du cluster)")


@router.post("/nodes/{node}/services/{service}/{action}", status_code=status.HTTP_202_ACCEPTED)
async def service_action(body: ServiceAction, conn_id: int, node: str = Path(pattern=NODE),
                         service: str = Path(pattern=r"^[a-z0-9][a-z0-9-]{0,40}$"), action: Literal["start", "stop", "restart", "reload"] = Path(),
                         db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                         user: AdminUser = Depends(current_user)):
    target, act = f"service/{service}@{node}", f"service-{action}"
    refused = verdict(service, action, body.confirm, body.type_name)
    if refused:
        audit.record(db, username=user.username, connection_id=conn_id, action=act, target=target, status="error", detail=refused[1])
        raise HTTPException(*refused)
    try:
        upid = await _px(db, factory, conn_id, "post", f"/nodes/{node}/services/{service}/{action}")
    except HTTPException as e:
        audit.record(db, username=user.username, connection_id=conn_id, action=act, target=target, status="error", detail=str(e.detail))
        raise
    audit.record(db, username=user.username, connection_id=conn_id, action=act, target=target, status="started", upid=upid if isinstance(upid, str) else None)
    return {"upid": upid if isinstance(upid, str) else None, "node": node}
