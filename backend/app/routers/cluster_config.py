"""Cluster Proxmox (corosync) en LECTURE SEULE : nœuds, totem, QDevice, quorum. Créer, joindre, retirer un nœud : voir `docs/m10-cluster.md` (non implémenté).

Une sous-requête qui échoue (droit `Sys.Audit` manquant, nœud isolé sans cluster) n'empêche pas les autres : son message court est rendu dans `errors`.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..clusterspec import merge_nodes, shape_corosync_nodes, shape_join, shape_qdevice, shape_status, shape_totem
from ..db import get_db
from ..deps import get_client_factory
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["cluster-config"], dependencies=[Depends(current_user)])


@router.get("/cluster/config")
async def cluster_config(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Résumé du cluster : quorum, version de la configuration, nœuds (état + votes + liens corosync), totem, QDevice, informations pour joindre un nœud."""
    errors: dict[str, str] = {}

    async def part(name: str, path: str):
        try:
            return await _px(db, factory, conn_id, "get", path)
        except HTTPException as e:
            errors[name] = str(e.detail)[:200]
            return None

    status = shape_status(await part("status", "/cluster/status"))
    corosync = shape_corosync_nodes(await part("nodes", "/cluster/config/nodes"))
    totem = shape_totem(await part("totem", "/cluster/config/totem"))
    qdevice = shape_qdevice(await part("qdevice", "/cluster/config/qdevice"))
    join_raw = await part("join", "/cluster/config/join")
    join = shape_join(join_raw)
    join_nodes = shape_corosync_nodes(join_raw.get("nodelist")) if isinstance(join_raw, dict) else []
    return {"cluster": {k: v for k, v in status.items() if k != "nodes"}, "nodes": merge_nodes(status["nodes"], corosync, join_nodes), "totem": totem, "qdevice": qdevice, "join": join, "errors": errors}
