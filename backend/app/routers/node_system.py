"""Système d'un nœud (lecture seule) : état, heure, DNS, services, mises à jour, dépôts, certificats, disques, journal."""
import asyncio

import httpx
from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from .. import systemspec as S
from ..db import get_db
from ..deps import get_client_factory
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _get_or_404, _params, http_error

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["node-system"], dependencies=[Depends(current_user)])

# rubrique -> (chemin Proxmox relatif au nœud, mise en forme). Constantes : aucune saisie n'entre dans l'appel.
SECTIONS = {
    "status": ("status", S.shape_status), "time": ("time", S.shape_time), "dns": ("dns", S.shape_dns),
    "services": ("services", S.shape_services), "updates": ("apt/update", S.shape_updates), "versions": ("apt/versions", S.shape_versions),
    "repositories": ("apt/repositories", S.shape_repositories), "certificates": ("certificates/info", S.shape_certificates),
    "disks": ("disks/list", S.shape_disks), "subscription": ("subscription", S.shape_subscription),
}


async def _section(client, node: str, name: str) -> dict:
    path, shape = SECTIONS[name]
    try:
        return {"state": "ok", "data": shape(await client.get(f"/nodes/{node}/{path}"))}
    except httpx.HTTPStatusError as e:
        return {"state": "forbidden" if e.response.status_code == 403 else "error", "data": None}
    except httpx.HTTPError:
        return {"state": "error", "data": None}


@router.get("/nodes/{node}/system")
async def node_system(conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Rubriques du système du nœud. Chacune est `{state: ok|forbidden|error, data}` : un droit manquant (`forbidden`) n'empêche pas les autres."""
    client = factory(**_params(_get_or_404(db, conn_id)))
    try:
        names = list(SECTIONS)
        results = await asyncio.gather(*(_section(client, node, n) for n in names))
    finally:
        await client.aclose()
    out = dict(zip(names, results))
    if all(r["state"] == "error" for r in results):
        raise http_error(httpx.ConnectError("injoignable"))
    return out


@router.get("/nodes/{node}/syslog")
async def node_syslog(conn_id: int, node: str = Path(pattern=NODE), limit: int = Query(default=100, ge=1, le=S.SYSLOG_MAX),
                      since: str | None = Query(default=None, pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"), db: Session = Depends(get_db),
                      factory: Factory = Depends(get_client_factory)):
    """Dernières lignes du journal système (droit `Sys.Syslog`). Lecture seule."""
    # Proxmox lit le journal depuis son début : on demande d'abord le total (1 ligne), puis la fin.
    extra = {"since": since} if since else {}
    client = factory(**_params(_get_or_404(db, conn_id)))
    try:
        _, total = await client.get_with_total(f"/nodes/{node}/syslog", limit=1, **extra)
        start = max(0, total - limit) if total is not None else 0
        rows = await client.get(f"/nodes/{node}/syslog", limit=limit, start=start, **extra)
    except httpx.HTTPError as e:
        raise http_error(e)
    finally:
        await client.aclose()
    return {"lines": S.shape_syslog(rows, limit), "total": total}
