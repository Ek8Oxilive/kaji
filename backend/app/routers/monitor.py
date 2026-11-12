"""Moniteur QEMU d'une VM en lecture seule (`qm monitor`, commandes « info … » seulement), lot #273.

`POST …/qemu/{vmid}/monitor {command}` : la commande doit figurer EXACTEMENT dans la liste blanche de `monitorspec.py` (jamais une commande libre) ;
la VM doit être en marche (état relu chez Proxmox) ; la sortie est nettoyée et bornée. Audit `qemu-monitor` (la commande, jamais la sortie).
Droit Proxmox : `VM.Monitor`. La route a la forme de la route générique `{action}` de `actions.py` (`ORDER = 90`) : ce module passe avant elle.
"""
from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..monitorspec import COMMANDS, check_command, clean_output
from .actions import NODE
from .auth import current_user
from .cluster import FORBIDDEN_DETAIL, Factory, _px

router = APIRouter(tags=["monitor"], dependencies=[Depends(current_user)])
BASE = "/api/connections/{conn_id}/guests/{node}/qemu/{vmid}/monitor"
# Constaté en réel (Proxmox 9.1.9, token avec PVEVMAdmin et Sys.Modify) : le moniteur est refusé (403) ; `VM.Monitor` n'existe plus dans les rôles.
DENIED = ("Proxmox refuse le moniteur QEMU au token de Kaji (observé en réel sur Proxmox 9 : probablement réservé à root@pam). "
          "Utilise `qm monitor` sur le nœud, dans la console.")


class MonitorBody(BaseModel):
    """Seul `command` existe : tout autre champ est ignoré et jamais transmis à Proxmox."""
    command: str = Field(max_length=100)


@router.get(BASE)
def monitor_commands(conn_id: int, node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999)):
    """Commandes autorisées (liste blanche, lecture seule)."""
    return {"commands": [{"command": c, "label": label} for c, label in COMMANDS.items()]}


@router.post(BASE)
async def run_monitor(body: MonitorBody, conn_id: int, node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999),
                      db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    target = f"qemu/{vmid}@{node}"

    def log(st, detail=None):
        audit.record(db, username=user.username, connection_id=conn_id, action="qemu-monitor", target=target, status=st, detail=detail)

    def refuse(msg: str, code: int, detail: str | None = None):
        log("error", detail or msg)
        raise HTTPException(code, msg)

    async def px(method: str, path: str, **kw):
        try:
            return await _px(db, factory, conn_id, method, path, **kw)
        except HTTPException as e:
            if method == "post" and e.detail == FORBIDDEN_DETAIL:         # le refus de Proxmox sur la commande elle-même
                e = HTTPException(status.HTTP_403_FORBIDDEN, DENIED)
            log("error", str(e.detail))
            raise e

    command = check_command(body.command)
    if command is None:
        refuse("Commande non autorisée : seules les commandes « info … » de la liste sont acceptées", 422, "commande hors liste blanche")
    current = await px("get", f"/nodes/{node}/qemu/{vmid}/status/current")
    if not isinstance(current, dict):
        refuse("État de la machine illisible", 502)
    if current.get("status") != "running":
        refuse("La VM doit être en marche pour interroger le moniteur QEMU", 409)
    output = await px("post", f"/nodes/{node}/qemu/{vmid}/monitor", command=command)
    text, truncated = clean_output(output)
    log("started", command)
    return {"command": command, "output": text, "truncated": truncated}
