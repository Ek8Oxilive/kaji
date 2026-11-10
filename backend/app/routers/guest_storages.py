"""Quels stockages utilise chaque machine (lecture seule, pour le regroupement « par stockage » du tableau de bord).

Aucune route de Proxmox ne donne directement « machine -> stockages » : on lit les volumes de chaque stockage actif qui peut contenir des disques
(`images`, `rootdir`) et on retient leur `vmid`. Un stockage partagé n'est lu qu'une fois ; un stockage illisible est compté dans `errors`, sans
faire échouer le reste.
"""
import asyncio

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_client_factory
from ..storagespec import shape_storages, shape_volumes
from .auth import current_user
from .cluster import Factory, _px_get

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["guest-storages"], dependencies=[Depends(current_user)])

DISK_CONTENTS = ("images", "rootdir")
MAX_STORAGES = 40                      # borne : jamais plus d'appels que cela vers Proxmox pour une seule requête


@router.get("/guest-storages")
async def guest_storages(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """`{by_vmid: {"102": ["local-lvm"], …}, storages: […], errors: n}` : stockages portant les disques de chaque machine."""
    rows = shape_storages(await _px_get(db, factory, conn_id, "/cluster/resources", type="storage"))
    targets: list[tuple[str, str]] = []
    shared_seen: set[str] = set()
    for r in rows:
        if not r["active"] or not r["node"] or not set(DISK_CONTENTS) & set(r["contents"]):
            continue
        if r["shared"]:
            if r["storage"] in shared_seen:
                continue
            shared_seen.add(r["storage"])
        targets.append((r["node"], r["storage"]))
    skipped = max(0, len(targets) - MAX_STORAGES)
    targets = targets[:MAX_STORAGES]

    async def read(node: str, storage: str):
        return shape_volumes(await _px_get(db, factory, conn_id, f"/nodes/{node}/storage/{storage}/content"))

    results = await asyncio.gather(*(read(n, s) for n, s in targets), return_exceptions=True)
    by: dict[int, set[str]] = {}
    errors = skipped
    for (_, storage), res in zip(targets, results):
        if isinstance(res, BaseException):
            errors += 1
            continue
        for v in res:
            if v["vmid"] is not None and v["content"] in DISK_CONTENTS:
                by.setdefault(v["vmid"], set()).add(storage)
    return {"by_vmid": {str(k): sorted(v) for k, v in sorted(by.items())}, "storages": sorted({s for _, s in targets}), "errors": errors}
