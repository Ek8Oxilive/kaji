"""Édition du matériel des VM/LXC (niveau A : CPU, RAM, réseau, ISO, agrandissement de disque)."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..hardware import BOOT_KEY, BRIDGE, DISK_KEY, ISO, MP_KEY, NET_KEY, normalize, parse_disk, rebuild_net
from ..models import AdminUser
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(tags=["hardware"], dependencies=[Depends(current_user)])
BASE = "/api/connections/{conn_id}/guests/{node}/{gtype}/{vmid}"


class NetEdit(BaseModel):
    bridge: str | None = None
    tag: int | None = Field(default=None, ge=1, le=4094)
    clear_tag: bool = False
    firewall: bool | None = None

    @field_validator("bridge")
    @classmethod
    def _bridge(cls, v):
        if v is not None and not BRIDGE.fullmatch(v):
            raise ValueError("Nom de bridge invalide")
        return v


class CdromEdit(BaseModel):
    iso: str | None = Field(default=None, description="ex. local:iso/debian.iso ; null pour éjecter")

    @field_validator("iso")
    @classmethod
    def _iso(cls, v):
        if v is not None and not ISO.fullmatch(v):
            raise ValueError("Volume ISO invalide (attendu : stockage:iso/nom.iso)")
        return v


class ConfigUpdate(BaseModel):
    memory: int | None = Field(default=None, ge=16, le=4_194_304, description="Mo")
    balloon: int | None = Field(default=None, ge=0, le=4_194_304, description="Mo, 0 = désactivé (VM)")
    cores: int | None = Field(default=None, ge=1, le=512)
    sockets: int | None = Field(default=None, ge=1, le=8, description="VM")
    cpu: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_\-]{1,40}$", description="type de CPU (VM)")
    swap: int | None = Field(default=None, ge=0, le=4_194_304, description="Mo (LXC)")
    nets: dict[str, NetEdit] = {}
    cdroms: dict[str, CdromEdit] = {}
    boot: list[str] | None = Field(default=None, min_length=1, max_length=40, description="Ordre de démarrage (VM) : scsi0, ide2, net0…")

    @field_validator("boot")
    @classmethod
    def _boot(cls, v):
        if v is not None and (len(set(v)) != len(v) or not all(BOOT_KEY.fullmatch(x) for x in v)):
            raise ValueError("Ordre de démarrage invalide (périphériques uniques : scsi0, ide2, net0…)")
        return v


class ResizeBody(BaseModel):
    disk: str
    add_gb: int = Field(ge=1, le=4096)
    confirm: bool = False


def _target(conn_id: int, node: str, gtype: str, vmid: int):
    return f"/nodes/{node}/{gtype}/{vmid}", f"{gtype}/{vmid}@{node}"


@router.get(BASE + "/config")
async def get_config(conn_id: int, node: str = Path(pattern=NODE), gtype: Literal["qemu", "lxc"] = Path(),
                     vmid: int = Path(ge=100, le=999999999), db: Session = Depends(get_db),
                     factory: Factory = Depends(get_client_factory)):
    """Matériel d'une machine, décomposé en champs, avec les changements en attente."""
    path, _ = _target(conn_id, node, gtype, vmid)
    cfg = await _px(db, factory, conn_id, "get", f"{path}/config", current=1)
    pending = await _px(db, factory, conn_id, "get", f"{path}/pending")
    return normalize(gtype, cfg, pending if isinstance(pending, list) else [])


@router.patch(BASE + "/config")
async def update_config(body: ConfigUpdate, conn_id: int, node: str = Path(pattern=NODE),
                        gtype: Literal["qemu", "lxc"] = Path(), vmid: int = Path(ge=100, le=999999999),
                        db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                        user: AdminUser = Depends(current_user)):
    path, target = _target(conn_id, node, gtype, vmid)
    lxc = gtype == "lxc"

    def refuse(msg: str, code: int = 422):
        audit.record(db, username=user.username, connection_id=conn_id, action="config", target=target,
                     status="error", detail=msg)
        raise HTTPException(code, msg)

    async def px(method: str, p: str, **kw):
        """Appel Proxmox dont l'échec (droits, réseau…) est toujours journalisé."""
        try:
            return await _px(db, factory, conn_id, method, p, **kw)
        except HTTPException as e:
            audit.record(db, username=user.username, connection_id=conn_id, action="config", target=target,
                         status="error", detail=str(e.detail))
            raise

    if lxc and (body.balloon is not None or body.sockets is not None or body.cpu is not None or body.cdroms or body.boot):
        refuse("Option réservée aux VM (balloon, sockets, cpu, cdroms, boot)")
    if not lxc and body.swap is not None:
        refuse("Le swap ne concerne que les LXC")

    params: dict[str, str | int] = {k: v for k, v in body.model_dump(include={"memory", "balloon", "cores", "sockets", "cpu", "swap"}).items() if v is not None}
    cfg = await px("get", f"{path}/config", current=1)

    for key, edit in body.nets.items():
        if not NET_KEY.fullmatch(key) or key not in cfg:
            refuse(f"Carte réseau inconnue : {key}", 404)
        tag = None if edit.clear_tag else (edit.tag if edit.tag is not None else False)
        params[key] = rebuild_net(cfg[key], lxc, bridge=edit.bridge, tag=tag, firewall=edit.firewall)
    for key, edit in body.cdroms.items():
        if key not in cfg or not DISK_KEY.fullmatch(key) or parse_disk(key, cfg[key])["kind"] != "cdrom":
            refuse(f"Lecteur CD/DVD inconnu : {key}", 404)
        params[key] = f"{edit.iso},media=cdrom" if edit.iso else "none,media=cdrom"

    if body.boot is not None:
        missing = [k for k in body.boot if k not in cfg]
        if missing:
            refuse(f"Périphérique de démarrage inconnu : {', '.join(missing)}", 404)
        params["boot"] = "order=" + ";".join(body.boot)

    if not params:
        refuse("Aucune modification demandée", 400)
    await px("put", f"{path}/config", **params)
    audit.record(db, username=user.username, connection_id=conn_id, action="config", target=target,
                 status="started", detail=", ".join(f"{k}={v}" for k, v in params.items()))
    return {"changed": sorted(params)}


@router.post(BASE + "/resize", status_code=status.HTTP_202_ACCEPTED)
async def resize_disk(body: ResizeBody, conn_id: int, node: str = Path(pattern=NODE),
                      gtype: Literal["qemu", "lxc"] = Path(), vmid: int = Path(ge=100, le=999999999),
                      db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                      user: AdminUser = Depends(current_user)):
    """Agrandit un disque de N Go. Irréversible : Proxmox ne sait pas réduire un disque."""
    path, target = _target(conn_id, node, gtype, vmid)

    def refuse(msg: str, code: int):
        audit.record(db, username=user.username, connection_id=conn_id, action="resize", target=f"{target}:{body.disk}",
                     status="error", detail=msg)
        raise HTTPException(code, msg)

    async def px(method: str, p: str, **kw):
        try:
            return await _px(db, factory, conn_id, method, p, **kw)
        except HTTPException as e:
            audit.record(db, username=user.username, connection_id=conn_id, action="resize",
                         target=f"{target}:{body.disk}", status="error", detail=str(e.detail))
            raise

    if not body.confirm:
        refuse("L'agrandissement d'un disque est irréversible : renvoie la requête avec {\"confirm\": true}", 400)
    cfg = await px("get", f"{path}/config", current=1)
    is_disk = (body.disk == "rootfs" or bool(MP_KEY.fullmatch(body.disk))) if gtype == "lxc" else bool(DISK_KEY.fullmatch(body.disk))
    if not is_disk or body.disk not in cfg or parse_disk(body.disk, cfg[body.disk])["kind"] != "disk":
        refuse(f"Disque inconnu : {body.disk}", 404)
    await px("put", f"{path}/resize", disk=body.disk, size=f"+{body.add_gb}G")
    audit.record(db, username=user.username, connection_id=conn_id, action="resize", target=f"{target}:{body.disk}",
                 status="started", detail=f"+{body.add_gb}G")
    return {"disk": body.disk, "added_gb": body.add_gb}
