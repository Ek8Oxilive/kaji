"""Ajout et retrait de cartes réseau d'une VM ou d'un LXC."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..hardware import BRIDGE, NET_KEY, build_new_net, next_net_index, parse_net
from ..models import AdminUser
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(tags=["nets"], dependencies=[Depends(current_user)])
BASE = "/api/connections/{conn_id}/guests/{node}/{gtype}/{vmid}/nets"


class NetAdd(BaseModel):
    bridge: str
    model: Literal["virtio", "e1000", "e1000e", "rtl8139", "vmxnet3"] = "virtio"
    tag: int | None = Field(default=None, ge=1, le=4094)
    firewall: bool = False
    ip: str | None = Field(default=None, max_length=64, description="LXC : dhcp, manual ou adresse CIDR")
    gateway: str | None = Field(default=None, max_length=64, description="LXC : passerelle (avec une IP statique)")

    @field_validator("bridge")
    @classmethod
    def _bridge(cls, v):
        if not BRIDGE.fullmatch(v):
            raise ValueError("Nom de bridge invalide")
        return v


@router.post(BASE, status_code=status.HTTP_201_CREATED)
async def add_net(body: NetAdd, conn_id: int, node: str = Path(pattern=NODE), gtype: Literal["qemu", "lxc"] = Path(),
                  vmid: int = Path(ge=100, le=999999999), db: Session = Depends(get_db),
                  factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Ajoute une carte réseau (la MAC est attribuée par Proxmox). Prend effet à chaud ou au redémarrage selon la machine."""
    path, target = f"/nodes/{node}/{gtype}/{vmid}/config", f"{gtype}/{vmid}@{node}"
    lxc = gtype == "lxc"

    def audit_err(msg):
        audit.record(db, username=user.username, connection_id=conn_id, action="net-add", target=target, status="error", detail=msg)

    async def px(method, p, **kw):
        try:
            return await _px(db, factory, conn_id, method, p, **kw)
        except HTTPException as e:
            audit_err(str(e.detail))
            raise

    if not lxc and (body.ip or body.gateway):
        audit_err("IP et passerelle ne concernent que les LXC")
        raise HTTPException(422, "IP et passerelle ne concernent que les LXC")
    cfg = await px("get", path, current=1)
    try:
        index = next_net_index(cfg)
        value = build_new_net(lxc, index, bridge=body.bridge, model=body.model, tag=body.tag,
                              firewall=body.firewall, ip=body.ip, gateway=body.gateway)
    except ValueError as e:
        audit_err(str(e))
        raise HTTPException(422, str(e))
    await px("put", path, **{f"net{index}": value})
    audit.record(db, username=user.username, connection_id=conn_id, action="net-add", target=target,
                 status="started", detail=f"net{index}: {value}")
    return {"key": f"net{index}", "value": value}


@router.delete(BASE + "/{key}", status_code=status.HTTP_200_OK)
async def remove_net(conn_id: int, key: str = Path(pattern=r"^net\d+$"), node: str = Path(pattern=NODE),
                     gtype: Literal["qemu", "lxc"] = Path(), vmid: int = Path(ge=100, le=999999999),
                     confirm: bool = Query(default=False), db: Session = Depends(get_db),
                     factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Retire une carte réseau. La MAC est perdue : une nouvelle carte en recevra une autre."""
    path, target = f"/nodes/{node}/{gtype}/{vmid}/config", f"{gtype}/{vmid}@{node}:{key}"

    def audit_err(msg):
        audit.record(db, username=user.username, connection_id=conn_id, action="net-remove", target=target, status="error", detail=msg)

    async def px(method, p, **kw):
        try:
            return await _px(db, factory, conn_id, method, p, **kw)
        except HTTPException as e:
            audit_err(str(e.detail))
            raise

    if not confirm:
        audit_err("confirmation manquante")
        raise HTTPException(400, "Retirer une carte réseau perd son adresse MAC : renvoie la requête avec ?confirm=true")
    cfg = await px("get", path, current=1)
    if key not in cfg or not NET_KEY.fullmatch(key):
        audit_err("carte inconnue")
        raise HTTPException(404, f"Carte réseau inconnue : {key}")
    mac = parse_net(key, cfg[key], gtype == "lxc")["mac"]
    await px("put", path, delete=key)
    audit.record(db, username=user.username, connection_id=conn_id, action="net-remove", target=target,
                 status="started", detail=f"MAC {mac}" if mac else None)
    return {"removed": key}
