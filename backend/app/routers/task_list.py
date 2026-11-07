"""Journal des tâches (lecture seule) : liste des tâches de tous les nœuds. L'état et le journal d'une tâche sont dans `actions.py`."""
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_client_factory
from ..taskspec import TYPE_FILTER, merge_tasks, shape_task
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px
from .connections import _get_or_404

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["tasks"], dependencies=[Depends(current_user)])

MAX_NODES = 32
_NODE = re.compile(NODE)


@router.get("/tasks")
async def list_tasks(
        conn_id: int,
        node: str | None = Query(default=None, pattern=NODE, description="Un seul nœud ; sinon tous les nœuds en ligne"),
        limit: int = Query(default=100, ge=1, le=500, description="Nombre maximal de tâches (les plus récentes d'abord)"),
        errors: bool = Query(default=False, description="Seulement les tâches échouées"),
        running: bool = Query(default=False, description="Seulement les tâches en cours"),
        vmid: int | None = Query(default=None, ge=100, le=999999999),
        type: str | None = Query(default=None, pattern=f"^{TYPE_FILTER.pattern}$", description="Type de tâche (qmstart, vzdump…)"),
        db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Tâches Proxmox, tous nœuds confondus, fusionnées et triées. Un nœud qui ne répond pas n'empêche pas les autres : il est listé
    dans `failed`. Lecture seule. `by_kaji` repère les tâches lancées par le jeton de cette connexion."""
    conn = _get_or_404(db, conn_id)
    if node:
        names = [node]
    else:
        data = await _px(db, factory, conn_id, "get", "/nodes")
        names = sorted(n["node"] for n in data if isinstance(n, dict) and n.get("status") == "online" and isinstance(n.get("node"), str)
                       and _NODE.fullmatch(n["node"]))[:MAX_NODES] if isinstance(data, list) else []
        if not names:
            raise HTTPException(503, "Aucun nœud en ligne pour lister les tâches")
    params: dict = {"limit": limit}
    if errors:
        params["errors"] = 1
    # Par défaut Proxmox ne renvoie que les tâches ARCHIVÉES (terminées) : sans `source=all`, les tâches en cours seraient absentes.
    params["source"] = "active" if running else "all"
    if vmid is not None:
        params["vmid"] = vmid
    if type:
        params["typefilter"] = type

    per_node, failed, first_error = [], [], None
    for n in names:
        try:
            rows = await _px(db, factory, conn_id, "get", f"/nodes/{n}/tasks", **params)
        except HTTPException as e:
            failed.append({"node": n, "reason": str(e.detail)[:200]})
            first_error = first_error or e
            continue
        per_node.append([t for t in (shape_task(r, n, conn.user, conn.token_id) for r in (rows if isinstance(rows, list) else [])) if t])
    if not per_node and first_error is not None:
        raise first_error                       # aucun nœud n'a répondu : l'erreur, pas une liste vide trompeuse
    return {"tasks": merge_tasks(per_node, limit), "failed": failed}
