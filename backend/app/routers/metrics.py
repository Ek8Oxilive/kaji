"""Historique des mesures (lecture seule) : séries RRD d'un nœud et d'une machine."""
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_client_factory
from ..metricspec import GUEST_FIELDS, NODE_FIELDS, shape_points, step_seconds
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["metrics"], dependencies=[Depends(current_user)])

Timeframe = Literal["hour", "day", "week", "month", "year"]


def _answer(timeframe: str, rows, fields: dict[str, str]) -> dict:
    points = shape_points(rows, fields)
    return {"timeframe": timeframe, "step": step_seconds(points), "points": points}


@router.get("/nodes/{node}/metrics")
async def node_metrics(conn_id: int, node: str = Path(pattern=NODE), timeframe: Timeframe = Query(default="hour"),
                       db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Processeur, charge, mémoire, swap et réseau d'un nœud dans le temps. Lecture seule. Valeurs absentes : `null`."""
    return _answer(timeframe, await _px(db, factory, conn_id, "get", f"/nodes/{node}/rrddata", timeframe=timeframe, cf="AVERAGE"),
                   NODE_FIELDS)


@router.get("/guests/{node}/{gtype}/{vmid}/metrics")
async def guest_metrics(conn_id: int, node: str = Path(pattern=NODE), gtype: Literal["qemu", "lxc"] = Path(),
                        vmid: int = Path(ge=100, le=999999999), timeframe: Timeframe = Query(default="hour"),
                        db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Processeur, mémoire, réseau et disque d'une machine dans le temps. Lecture seule. Valeurs absentes : `null`."""
    return _answer(timeframe, await _px(db, factory, conn_id, "get", f"/nodes/{node}/{gtype}/{vmid}/rrddata", timeframe=timeframe, cf="AVERAGE"),
                   GUEST_FIELDS)
