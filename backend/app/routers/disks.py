"""Disques d'une VM ou d'un LXC : ajouter, détacher, rattacher, supprimer pour de bon, déplacer."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..hardware import DISK_KEY, MP_KEY, UNUSED_KEY, build_new_disk, check_mp_path, next_disk_key, next_mp_key, parse_disk
from ..models import AdminUser
from ..vmspec import STORAGE
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(tags=["disks"], dependencies=[Depends(current_user)])
BASE = "/api/connections/{conn_id}/guests/{node}/{gtype}/{vmid}/disks"


def _storage(v: str) -> str:
    if not STORAGE.fullmatch(v):
        raise ValueError("Nom de stockage invalide")
    return v


class DiskAdd(BaseModel):
    storage: str
    size_gb: int = Field(ge=1, le=65536)
    bus: Literal["scsi", "virtio", "sata", "ide"] = "scsi"
    mp: str | None = Field(default=None, max_length=200, description="LXC : chemin de montage dans le conteneur")
    _s = field_validator("storage")(lambda cls, v: _storage(v))


class Reattach(BaseModel):
    bus: Literal["scsi", "virtio", "sata", "ide"] = "scsi"
    mp: str | None = Field(default=None, max_length=200)


class Move(BaseModel):
    storage: str
    delete_source: bool = False
    confirm: bool = False
    _s = field_validator("storage")(lambda cls, v: _storage(v))


def _is_disk_key(gtype: str, key: str) -> bool:
    return (key == "rootfs" or bool(MP_KEY.fullmatch(key))) if gtype == "lxc" else bool(DISK_KEY.fullmatch(key))


class Ctx:
    """Contexte d'une opération : appels Proxmox et audit, toujours journalisés."""

    def __init__(self, db, factory, user, conn_id, node, gtype, vmid, action):
        self.db, self.factory, self.user, self.conn_id, self.action = db, factory, user, conn_id, action
        self.path = f"/nodes/{node}/{gtype}/{vmid}"
        self.target = f"{gtype}/{vmid}@{node}"
        self.gtype = gtype
        self.node = node

    def log(self, st, detail=None, upid=None, target=None):
        audit.record(self.db, username=self.user.username, connection_id=self.conn_id, action=self.action,
                     target=target or self.target, status=st, detail=detail, upid=upid)

    def refuse(self, msg, code):
        self.log("error", msg)
        raise HTTPException(code, msg)

    async def px(self, method, path, **kw):
        try:
            return await _px(self.db, self.factory, self.conn_id, method, path, **kw)
        except HTTPException as e:
            self.log("error", str(e.detail))
            raise

    async def config(self):
        return await self.px("get", f"{self.path}/config", current=1)


def _ctx(action, conn_id, node, gtype, vmid, db, factory, user):
    return Ctx(db, factory, user, conn_id, node, gtype, vmid, action)


@router.post(BASE, status_code=status.HTTP_201_CREATED)
async def add_disk(body: DiskAdd, conn_id: int, node: str = Path(pattern=NODE), gtype: Literal["qemu", "lxc"] = Path(),
                   vmid: int = Path(ge=100, le=999999999), db: Session = Depends(get_db),
                   factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Crée un nouveau disque (VM : sur un bus libre ; LXC : point de montage, chemin obligatoire)."""
    c = _ctx("disk-add", conn_id, node, gtype, vmid, db, factory, user)
    lxc = gtype == "lxc"
    if lxc and not body.mp:
        c.refuse("Un chemin de montage est obligatoire pour un LXC (ex. /srv/data)", 422)
    if not lxc and body.mp:
        c.refuse("Le chemin de montage ne concerne que les LXC", 422)
    cfg = await c.config()
    try:
        key = next_mp_key(cfg) if lxc else next_disk_key(cfg, body.bus)
        value = build_new_disk(body.storage, body.size_gb, body.mp if lxc else None)
    except ValueError as e:
        c.refuse(str(e), 422)
    await c.px("put", f"{c.path}/config", **{key: value})
    c.log("started", f"{key}: {value}")
    return {"key": key, "value": value}


@router.post(BASE + "/{key}/detach")
async def detach_disk(conn_id: int, key: str = Path(pattern=r"^[a-z]+\d*$"), node: str = Path(pattern=NODE),
                      gtype: Literal["qemu", "lxc"] = Path(), vmid: int = Path(ge=100, le=999999999),
                      db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                      user: AdminUser = Depends(current_user)):
    """Détache un disque : il devient « non utilisé », les données sont conservées et il peut être rattaché de nouveau."""
    c = _ctx("disk-detach", conn_id, node, gtype, vmid, db, factory, user)
    c.target += f":{key}"
    if key == "rootfs":
        c.refuse("Le disque racine d'un LXC ne peut pas être détaché", 422)
    if not _is_disk_key(gtype, key):
        c.refuse(f"Disque inconnu : {key}", 404)
    cfg = await c.config()
    if key not in cfg or parse_disk(key, cfg[key])["kind"] != "disk":
        c.refuse(f"Disque inconnu : {key}", 404)
    await c.px("put", f"{c.path}/config", delete=key)
    c.log("started", f"{cfg[key]} (conservé, non utilisé)")
    return {"detached": key}


@router.post(BASE + "/{key}/reattach", status_code=status.HTTP_200_OK)
async def reattach_disk(body: Reattach, conn_id: int, key: str = Path(pattern=r"^unused\d+$"), node: str = Path(pattern=NODE),
                        gtype: Literal["qemu", "lxc"] = Path(), vmid: int = Path(ge=100, le=999999999),
                        db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                        user: AdminUser = Depends(current_user)):
    """Rattache un disque non utilisé à la machine."""
    c = _ctx("disk-reattach", conn_id, node, gtype, vmid, db, factory, user)
    c.target += f":{key}"
    lxc = gtype == "lxc"
    if lxc and not body.mp:
        c.refuse("Un chemin de montage est obligatoire pour un LXC", 422)
    cfg = await c.config()
    if key not in cfg or not UNUSED_KEY.fullmatch(key):
        c.refuse(f"Disque non utilisé inconnu : {key}", 404)
    try:
        new = next_mp_key(cfg) if lxc else next_disk_key(cfg, body.bus)
        value = cfg[key] + (f",mp={check_mp_path(body.mp)}" if lxc else "")
    except ValueError as e:
        c.refuse(str(e), 422)
    # ATTENTION : ne jamais envoyer « delete=unusedN » avec le rattachement. Proxmox traite le delete en premier et
    # DÉTRUIT le volume avant de tenter de le rattacher (constaté en réel). Seule la nouvelle clé est envoyée.
    await c.px("put", f"{c.path}/config", **{new: value})
    c.log("started", f"{key} -> {new}")
    return {"key": new}


@router.delete(BASE + "/{key}", status_code=status.HTTP_200_OK)
async def destroy_unused(conn_id: int, key: str = Path(pattern=r"^unused\d+$"), node: str = Path(pattern=NODE),
                         gtype: Literal["qemu", "lxc"] = Path(), vmid: int = Path(ge=100, le=999999999),
                         confirm: bool = Query(default=False), name: str = Query(default="", max_length=100),
                         db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                         user: AdminUser = Depends(current_user)):
    """Supprime DÉFINITIVEMENT un disque non utilisé (données détruites). Exige confirm=true et le nom exact de la machine."""
    c = _ctx("disk-destroy", conn_id, node, gtype, vmid, db, factory, user)
    c.target += f":{key}"
    if not confirm:
        c.refuse("Suppression définitive : renvoie la requête avec ?confirm=true et le nom de la machine (?name=)", 400)
    cfg = await c.config()
    if key not in cfg:
        c.refuse(f"Disque non utilisé inconnu : {key}", 404)
    machine = cfg.get("hostname" if gtype == "lxc" else "name")
    if not machine or name != machine:
        c.refuse("Le nom de la machine ne correspond pas : suppression refusée", 400)
    await c.px("put", f"{c.path}/config", delete=key)
    c.log("started", f"{cfg[key]} DÉTRUIT")
    return {"destroyed": key}


@router.post(BASE + "/{key}/move", status_code=status.HTTP_202_ACCEPTED)
async def move_disk(body: Move, conn_id: int, key: str = Path(pattern=r"^[a-z]+\d*$"), node: str = Path(pattern=NODE),
                    gtype: Literal["qemu", "lxc"] = Path(), vmid: int = Path(ge=100, le=999999999),
                    db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                    user: AdminUser = Depends(current_user)):
    """Déplace un disque vers un autre stockage. L'ancien emplacement est conservé comme disque non utilisé, sauf delete_source."""
    c = _ctx("disk-move", conn_id, node, gtype, vmid, db, factory, user)
    c.target += f":{key}"
    if not body.confirm:
        c.refuse("Le déplacement est long et copie tout le disque : renvoie la requête avec {\"confirm\": true}", 400)
    if not _is_disk_key(gtype, key):
        c.refuse(f"Disque inconnu : {key}", 404)
    cfg = await c.config()
    if key not in cfg or parse_disk(key, cfg[key])["kind"] != "disk":
        c.refuse(f"Disque inconnu : {key}", 404)
    if cfg[key].partition(":")[0] == body.storage:
        c.refuse("Le disque est déjà sur ce stockage", 422)
    params = {("volume" if gtype == "lxc" else "disk"): key, "storage": body.storage, "delete": 1 if body.delete_source else 0}
    upid = await c.px("post", f"{c.path}/{'move_volume' if gtype == 'lxc' else 'move_disk'}", **params)
    c.log("started", f"{cfg[key].partition(':')[0]} -> {body.storage}" + (" (source supprimée)" if body.delete_source else ""),
          upid=upid if isinstance(upid, str) else None)
    return {"upid": upid, "node": node}
