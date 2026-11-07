"""Disques d'un nœud (lecture seule) : disques, partitions, LVM, LVM-thin, répertoires, ZFS, SMART. Droit `Sys.Audit`."""
import asyncio

import httpx
from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from .. import diskspec as D
from ..db import get_db
from ..deps import get_client_factory
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _get_or_404, _params, _px, http_error

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["node-disks"], dependencies=[Depends(current_user)])

# rubrique -> (chemin relatif au nœud, paramètres constants, mise en forme). Aucune saisie n'entre dans ces appels.
SECTIONS = {
    "disks": ("disks/list", {"include-partitions": 1}, D.shape_disks), "lvm": ("disks/lvm", {}, D.shape_lvm),
    "lvmthin": ("disks/lvmthin", {}, D.shape_lvmthin), "directory": ("disks/directory", {}, D.shape_directories), "zfs": ("disks/zfs", {}, D.shape_zfs),
}


async def _section(client, node: str, name: str) -> dict:
    path, params, shape = SECTIONS[name]
    try:
        return {"state": "ok", "data": shape(await client.get(f"/nodes/{node}/{path}", **params))}
    except httpx.HTTPStatusError as e:
        return {"state": "forbidden" if e.response.status_code == 403 else "error", "data": None}
    except httpx.HTTPError:
        return {"state": "error", "data": None}


@router.get("/nodes/{node}/disks")
async def node_disks(conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Rubriques `{state: ok|forbidden|error, data}` indépendantes ; `502` seulement si toutes échouent."""
    client = factory(**_params(_get_or_404(db, conn_id)))
    try:
        names = list(SECTIONS)
        results = await asyncio.gather(*(_section(client, node, n) for n in names))
    finally:
        await client.aclose()
    if all(r["state"] == "error" for r in results):
        raise http_error(httpx.ConnectError("injoignable"))
    return dict(zip(names, results))


@router.get("/nodes/{node}/disks/smart")
async def node_smart(conn_id: int, node: str = Path(pattern=NODE), disk: str = Query(pattern=r"^/dev/[A-Za-z0-9]{1,30}$"),
                     db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """État SMART d'un disque (santé, usure, attributs ou texte brut borné)."""
    return D.shape_smart(await _px(db, factory, conn_id, "get", f"/nodes/{node}/disks/smart", disk=disk))
