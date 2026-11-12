"""Arrêter une tâche en cours (bouton Stop du journal d'une tâche de Proxmox), lot #310.

`DELETE …/tasks/{node}/{upid}?confirm=true` : l'UPID est validé, son nœud doit être celui du chemin, la tâche est relue chez Proxmox et doit être EN COURS, son type
doit figurer dans la liste blanche de `taskstopspec.py` et elle ne doit pas viser une machine de `KAJI_PROTECTED_VMIDS`. Droit Proxmox : être propriétaire de la tâche
ou `Sys.Modify` sur `/nodes/<nœud>`. Audit `task-stop` (succès, refus, erreurs). RIEN n'a été validé en réel au moment du code.
"""
from fastapi import APIRouter, Depends, HTTPException, Path, Query

from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..taskstopspec import STOPPABLE, parse_upid, stop_refusal
from .actions import NODE, UPID
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(tags=["task-stop"], dependencies=[Depends(current_user)])


@router.delete("/api/connections/{conn_id}/tasks/{node}/{upid}")
async def stop_task(conn_id: int, node: str = Path(pattern=NODE), upid: str = Path(max_length=300), confirm: bool = Query(default=False),
                    db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    target = f"{node}/{upid[:120]}"

    def log(st, detail=None):
        audit.record(db, username=user.username, connection_id=conn_id, action="task-stop", target=target, status=st, detail=detail)

    def refuse(msg: str, code: int, detail: str | None = None):
        log("error", detail or msg)
        raise HTTPException(code, msg)

    async def px(method: str, path: str, **kw):
        try:
            return await _px(db, factory, conn_id, method, path, **kw)
        except HTTPException as e:
            log("error", str(e.detail))
            raise

    if not UPID.fullmatch(upid):
        refuse("Identifiant de tâche (UPID) invalide", 422, "UPID invalide")
    task = parse_upid(upid)
    if task is None or task["node"] != node:
        refuse("Cette tâche n'appartient pas à ce nœud", 422, "nœud de l'UPID différent")
    if not confirm:
        refuse("Arrêter une tâche abandonne son travail en cours : renvoie la requête avec ?confirm=true", 400)
    if msg := stop_refusal(task, get_settings().protected_vmids):
        refuse(msg, 409, f"refusée ({task['type']})")
    st = await px("get", f"/nodes/{node}/tasks/{upid}/status")
    if not isinstance(st, dict):
        refuse("État de la tâche illisible", 502)
    if st.get("status") != "running":
        refuse("La tâche n'est plus en cours", 409)
    await px("delete", f"/nodes/{node}/tasks/{upid}")
    log("started", f"arrêt demandé : {STOPPABLE[task['type']]}")
    return {"stopped": True, "upid": upid, "node": node, "type": task["type"]}
