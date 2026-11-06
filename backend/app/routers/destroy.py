"""Suppression définitive d'une VM ou d'un LXC."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..deps import get_client_factory
from ..hardware import DISK_KEY, MP_KEY, UNUSED_KEY, parse_disk
from ..models import AdminUser
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(tags=["destroy"], dependencies=[Depends(current_user)])


def volumes_of(cfg: dict, gtype: str) -> list[str]:
    """Volumes que la suppression détruira : disques attachés (hors CD/DVD) et disques non utilisés."""
    out = []
    for k, v in cfg.items():
        is_disk = (k == "rootfs" or MP_KEY.fullmatch(k)) if gtype == "lxc" else DISK_KEY.fullmatch(k)
        if is_disk and parse_disk(k, v)["kind"] == "disk" and parse_disk(k, v)["volume"]:
            out.append(f"{k}={parse_disk(k, v)['storage']}:{parse_disk(k, v)['volume']}")
        elif UNUSED_KEY.fullmatch(k):
            out.append(f"{k}={v}")
    return out


@router.delete("/api/connections/{conn_id}/guests/{node}/{gtype}/{vmid}")
async def delete_guest(conn_id: int, node: str = Path(pattern=NODE), gtype: Literal["qemu", "lxc"] = Path(),
                       vmid: int = Path(ge=100, le=999999999), confirm: bool = Query(default=False),
                       name: str = Query(default="", max_length=100), purge: bool = Query(default=True),
                       destroy_unreferenced: bool = Query(default=False), db: Session = Depends(get_db),
                       factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Supprime DÉFINITIVEMENT une machine et ses disques. Exige : machine arrêtée, confirm=true, nom exact, non protégée."""
    target = f"{gtype}/{vmid}@{node}"

    def log(st, detail=None, upid=None):
        audit.record(db, username=user.username, connection_id=conn_id, action="guest-delete", target=target,
                     status=st, detail=detail, upid=upid)

    def refuse(msg, code):
        log("error", msg)
        raise HTTPException(code, msg)

    async def px(method, path, **kw):
        try:
            return await _px(db, factory, conn_id, method, path, **kw)
        except HTTPException as e:
            log("error", str(e.detail))
            raise

    if vmid in get_settings().protected_vmids:
        refuse(f"La machine #{vmid} est protégée par Kaji (KAJI_PROTECTED_VMIDS) : suppression impossible", 403)
    if not confirm:
        refuse("Suppression définitive : renvoie la requête avec ?confirm=true et le nom de la machine (?name=)", 400)

    base = f"/nodes/{node}/{gtype}/{vmid}"
    current = await px("get", f"{base}/status/current")
    if (current or {}).get("status") != "stopped":
        refuse("La machine doit être arrêtée avant d'être supprimée", 409)
    cfg = await px("get", f"{base}/config", current=1)
    if str(cfg.get("protection")) == "1":
        refuse("La machine est protégée dans Proxmox (option « protection ») : désactive-la d'abord", 409)
    machine = cfg.get("hostname" if gtype == "lxc" else "name")
    if not machine or name != machine:
        refuse("Le nom de la machine ne correspond pas : suppression refusée", 400)

    params: dict = {}
    if purge:
        params["purge"] = 1
    if destroy_unreferenced:
        params["destroy-unreferenced-disks"] = 1
    volumes = volumes_of(cfg, gtype)
    upid = await px("delete", base, **params)
    log("started", f"« {machine} » SUPPRIMÉE ; disques détruits : {', '.join(volumes) or 'aucun'}"
        + (" · purgée des sauvegardes/HA" if purge else ""), upid=upid if isinstance(upid, str) else None)
    return {"upid": upid, "node": node, "deleted": vmid}
