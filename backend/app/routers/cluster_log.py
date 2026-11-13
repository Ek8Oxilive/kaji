"""Journal du cluster (Datacenter → Journal du cluster) en LECTURE SEULE : `GET /cluster/log`. Droit `Sys.Syslog` sur `/` pour tout voir (sinon Proxmox filtre). Lot #401."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..clusterlogspec import MAX_ENTRIES, shape_log
from ..db import get_db
from ..deps import get_client_factory
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["cluster-log"], dependencies=[Depends(current_user)])


@router.get("/cluster/log")
async def cluster_log(conn_id: int, max: int = Query(default=100, ge=1, le=MAX_ENTRIES), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Dernières entrées du journal du cluster, plus récentes d'abord (`max` : 1 à 500)."""
    return {"entries": shape_log(await _px(db, factory, conn_id, "get", "/cluster/log", max=max))}
