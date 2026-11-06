"""Stockages Proxmox : contenu d'un stockage (lecture seule)."""
from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_client_factory
from ..storagespec import ContentType, shape_volumes
from ..vmspec import STORAGE
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px_get

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["storage"],
                   dependencies=[Depends(current_user)])


@router.get("/nodes/{node}/storage/{storage}/content")
async def storage_content(
        conn_id: int,
        node: str = Path(pattern=NODE),
        storage: str = Path(pattern=STORAGE.pattern),
        content: ContentType | None = Query(default=None, description="Filtrer par type de contenu"),
        db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Volumes d'un stockage (ISO, modèles, disques, sauvegardes…). Lecture seule."""
    params = {"content": content} if content else {}
    return shape_volumes(await _px_get(db, factory, conn_id,
                                       f"/nodes/{node}/storage/{storage}/content", **params))
