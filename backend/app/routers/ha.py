"""Haute disponibilité et réplication (LECTURE SEULE). Les écritures viennent après (verrous : cluster à 2 nœuds, machine de Kaji)."""
from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_client_factory
from ..haspec import JOB, shape_ha_resources, shape_ha_rules, shape_ha_status, shape_job_status, shape_jobs, shape_log
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px_get

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["ha"], dependencies=[Depends(current_user)])


@router.get("/ha/status")
async def ha_status(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Quorum, maître du gestionnaire, états des LRM, chien de garde (fencing) et services HA."""
    return shape_ha_status(await _px_get(db, factory, conn_id, "/cluster/ha/status/current"))


@router.get("/ha/resources")
async def ha_resources(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    return shape_ha_resources(await _px_get(db, factory, conn_id, "/cluster/ha/resources"))


@router.get("/ha/rules")
async def ha_rules(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    return shape_ha_rules(await _px_get(db, factory, conn_id, "/cluster/ha/rules"))


@router.get("/replication")
async def replication_jobs(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Jobs de réplication du cluster (configuration)."""
    return shape_jobs(await _px_get(db, factory, conn_id, "/cluster/replication"))


@router.get("/nodes/{node}/replication")
async def node_replication(conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """État des jobs de réplication dont ce nœud est la source."""
    return shape_job_status(await _px_get(db, factory, conn_id, f"/nodes/{node}/replication"))


@router.get("/nodes/{node}/replication/{job}/log")
async def replication_log(conn_id: int, node: str = Path(pattern=NODE), job: str = Path(pattern=JOB.pattern), limit: int = Query(default=200, ge=1, le=2000),
                          db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    return shape_log(await _px_get(db, factory, conn_id, f"/nodes/{node}/replication/{job}/log", limit=limit))
