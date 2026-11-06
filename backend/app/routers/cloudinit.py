"""Cloud-init d'une VM : utilisateur, mot de passe, clés SSH, réseau, DNS, lecteur cloud-init."""
import ipaddress
import re
from typing import Literal
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field, SecretStr, field_validator
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..hardware import find_cloudinit_key, validate_ip
from ..lxcspec import SSH_KEY
from ..models import AdminUser
from ..vmspec import STORAGE
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(tags=["cloudinit"], dependencies=[Depends(current_user)])
BASE = "/api/connections/{conn_id}/guests/{node}/qemu/{vmid}/cloudinit"
USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
DOMAIN = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.\-]{0,251}[A-Za-z0-9])?$")
IPCONF = re.compile(r"^ipconfig(\d|[12]\d|3[01])$")
CLEARABLE = Literal["user", "password", "ssh_keys", "nameserver", "searchdomain", "ipconfig0", "ipconfig1", "ipconfig2", "ipconfig3"]
PVE_KEY = {"user": "ciuser", "password": "cipassword", "ssh_keys": "sshkeys", "nameserver": "nameserver", "searchdomain": "searchdomain"}


class IpConf(BaseModel):
    mode: Literal["dhcp", "static", "none"]
    ip: str | None = Field(default=None, max_length=64, description="Adresse CIDR (mode static)")
    gateway: str | None = Field(default=None, max_length=64)


class CloudInitUpdate(BaseModel):
    user: str | None = Field(default=None, pattern=USER.pattern)
    password: SecretStr | None = Field(default=None, min_length=8, max_length=128, description="Secret : jamais renvoyé ni journalisé")
    ssh_keys: str | None = Field(default=None, max_length=8192)
    ipconfig: dict[str, IpConf] = {}
    nameserver: str | None = Field(default=None, max_length=200, description="Adresses IP séparées par des espaces")
    searchdomain: str | None = Field(default=None, max_length=253)
    upgrade: bool | None = None
    clear: list[CLEARABLE] = Field(default=[], max_length=20, description="Réglages à supprimer")

    @field_validator("ssh_keys")
    @classmethod
    def _keys(cls, v):
        if v is None:
            return None
        lines = [l.strip() for l in v.strip().splitlines() if l.strip()]
        if not lines or len(lines) > 8 or not all(SSH_KEY.fullmatch(l) for l in lines):
            raise ValueError("Clé SSH publique invalide (8 au plus, une par ligne ; utilise « clear » pour tout retirer)")
        return "\n".join(lines)

    @field_validator("ipconfig")
    @classmethod
    def _ipconf(cls, v):
        if not all(IPCONF.fullmatch(k) for k in v):
            raise ValueError("Clé ipconfigN invalide")
        return v

    @field_validator("nameserver")
    @classmethod
    def _ns(cls, v):
        if v is None:
            return None
        try:
            for a in v.split():
                ipaddress.ip_address(a)
        except ValueError:
            raise ValueError("Serveur DNS invalide (adresses IP séparées par des espaces)") from None
        if not v.split():
            raise ValueError("Serveur DNS vide (utilise « clear »)")
        return " ".join(v.split())

    @field_validator("searchdomain")
    @classmethod
    def _domain(cls, v):
        if v is not None and not DOMAIN.fullmatch(v):
            raise ValueError("Domaine de recherche invalide")
        return v


class DriveAdd(BaseModel):
    storage: str

    @field_validator("storage")
    @classmethod
    def _s(cls, v):
        if not STORAGE.fullmatch(v):
            raise ValueError("Nom de stockage invalide")
        return v


def ipconfig_value(c: IpConf) -> str:
    if c.mode == "dhcp":
        return "ip=dhcp"
    if c.mode == "none":
        return "ip=manual"
    if not c.ip:
        raise ValueError("Une adresse CIDR est obligatoire en mode statique")
    validate_ip(c.ip, c.gateway)
    if "/" not in c.ip:
        raise ValueError("Adresse CIDR attendue (ex. 192.168.1.50/24)")
    return f"ip={c.ip}" + (f",gw={c.gateway}" if c.gateway else "")


def build_params(body: CloudInitUpdate) -> tuple[dict, list[str]]:
    """(paramètres à écrire, réglages à supprimer). Le champ sshkeys doit être encodé en URL (format urlencoded de Proxmox)."""
    p: dict = {}
    if body.user is not None:
        p["ciuser"] = body.user
    if body.password is not None:
        p["cipassword"] = body.password.get_secret_value()
    if body.ssh_keys is not None:
        p["sshkeys"] = quote(body.ssh_keys, safe="")
    if body.nameserver is not None:
        p["nameserver"] = body.nameserver
    if body.searchdomain is not None:
        p["searchdomain"] = body.searchdomain
    if body.upgrade is not None:
        p["ciupgrade"] = 1 if body.upgrade else 0
    for k, c in body.ipconfig.items():
        p[k] = ipconfig_value(c)
    delete = [PVE_KEY.get(c, c) for c in body.clear]
    clash = [k for k in delete if k in p]
    if clash:
        raise ValueError(f"Réglage à la fois modifié et supprimé : {', '.join(clash)}")
    return p, delete


def parse_ipconfig(value: str) -> dict:
    opts = dict(x.partition("=")[::2] for x in str(value).split(",") if "=" in x)
    ip = opts.get("ip")
    return {"mode": "dhcp" if ip == "dhcp" else "none" if ip in (None, "manual") else "static",
            "ip": ip if ip not in (None, "dhcp", "manual") else None, "gateway": opts.get("gw")}


def shape(cfg: dict) -> dict:
    return {
        "has_drive": find_cloudinit_key(cfg) is not None, "drive": find_cloudinit_key(cfg),
        "user": cfg.get("ciuser"), "password_set": "cipassword" in cfg,          # la valeur n'est jamais lue ni renvoyée
        "ssh_keys": unquote(cfg["sshkeys"]).strip() if cfg.get("sshkeys") else None,
        "ipconfig": {k: parse_ipconfig(v) for k, v in sorted(cfg.items()) if IPCONF.fullmatch(k)},
        "nameserver": cfg.get("nameserver"), "searchdomain": cfg.get("searchdomain"),
        "upgrade": None if "ciupgrade" not in cfg else str(cfg["ciupgrade"]) == "1",
    }


class _Ctx:
    def __init__(self, db, factory, user, conn_id, node, vmid, action):
        self.db, self.factory, self.user, self.conn_id, self.action = db, factory, user, conn_id, action
        self.path, self.target = f"/nodes/{node}/qemu/{vmid}", f"qemu/{vmid}@{node}"

    def log(self, st, detail=None):
        audit.record(self.db, username=self.user.username, connection_id=self.conn_id, action=self.action,
                     target=self.target, status=st, detail=detail)

    def refuse(self, msg, code):
        self.log("error", msg)
        raise HTTPException(code, msg)

    async def px(self, method, path, **kw):
        try:
            return await _px(self.db, self.factory, self.conn_id, method, path, **kw)
        except HTTPException as e:
            self.log("error", str(e.detail))
            raise


@router.get(BASE)
async def get_cloudinit(conn_id: int, node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999),
                        db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    return shape(await _px(db, factory, conn_id, "get", f"/nodes/{node}/qemu/{vmid}/config", current=1))


@router.patch(BASE)
async def update_cloudinit(body: CloudInitUpdate, conn_id: int, node: str = Path(pattern=NODE),
                           vmid: int = Path(ge=100, le=999999999), db: Session = Depends(get_db),
                           factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Modifie les réglages cloud-init. Pris en compte au prochain démarrage de la VM."""
    c = _Ctx(db, factory, user, conn_id, node, vmid, "cloudinit-update")
    try:
        params, delete = build_params(body)
    except ValueError as e:
        c.refuse(str(e), 422)
    if not params and not delete:
        c.refuse("Aucune modification demandée", 400)
    if delete:
        params["delete"] = ",".join(delete)
    await c.px("put", f"{c.path}/config", **params)
    changed = sorted(k for k in params if k not in ("delete",))
    c.log("started", "modifié : " + ", ".join(k if k not in ("cipassword", "sshkeys") else {"cipassword": "mot de passe", "sshkeys": "clés SSH"}[k] for k in changed)
          + (f" · supprimé : {', '.join(delete)}" if delete else ""))
    return {"changed": changed, "cleared": delete}


@router.post(BASE + "/drive", status_code=status.HTTP_201_CREATED)
async def add_drive(body: DriveAdd, conn_id: int, node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999),
                    db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                    user: AdminUser = Depends(current_user)):
    """Ajoute le lecteur cloud-init (petit disque généré par Proxmox), sur un bus IDE libre."""
    c = _Ctx(db, factory, user, conn_id, node, vmid, "cloudinit-drive-add")
    cfg = await c.px("get", f"{c.path}/config", current=1)
    if find_cloudinit_key(cfg):
        c.refuse("Cette VM a déjà un lecteur cloud-init", 409)
    free = next((f"ide{i}" for i in (2, 0, 1, 3) if f"ide{i}" not in cfg), None)
    if not free:
        c.refuse("Aucun emplacement IDE libre pour le lecteur cloud-init", 409)
    await c.px("put", f"{c.path}/config", **{free: f"{body.storage}:cloudinit"})
    c.log("started", f"{free} sur {body.storage}")
    return {"key": free}


@router.delete(BASE + "/drive")
async def remove_drive(conn_id: int, node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999),
                       confirm: bool = Query(default=False), db: Session = Depends(get_db),
                       factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Retire le lecteur cloud-init (les réglages cloud-init de la VM sont conservés)."""
    c = _Ctx(db, factory, user, conn_id, node, vmid, "cloudinit-drive-remove")
    if not confirm:
        c.refuse("Renvoie la requête avec ?confirm=true", 400)
    cfg = await c.px("get", f"{c.path}/config", current=1)
    key = find_cloudinit_key(cfg)
    if not key:
        c.refuse("Cette VM n'a pas de lecteur cloud-init", 404)
    await c.px("put", f"{c.path}/config", delete=key)
    c.log("started", key)
    return {"removed": key}
