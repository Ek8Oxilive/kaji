"""Options fines d'un disque, d'une carte réseau et du CPU (onglet Matériel). Validation et risques : `app/hwopts.py` (lot #377).

Réécrit UNE chaîne de périphérique (volume, taille, MAC et options non gérées conservés) ou les clés CPU, par `PUT …/config` avec le `digest` de la
configuration lue (refus si elle a changé), puis relit la configuration : si Proxmox n'a pas enregistré, 502. Une machine de `KAJI_PROTECTED_VMIDS`
est refusée même confirmée ; les réglages risqués exigent `confirm`, décidé par le SERVEUR. `dry_run` montre le résultat sans rien écrire.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..deps import get_client_factory
from ..hwopts import DISK_KEY, NET_KEY, CpuOptions, DiskOptions, NetOptions, build_cpu, build_disk, build_net, disk_changes, split_opts
from ..models import AdminUser
from ..optionspec import DIGEST
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(tags=["hw-options"], dependencies=[Depends(current_user)])
B = "/api/connections/{conn_id}/guests/{node}"
CONFIRM = "Confirmation requise (renvoie la requête avec confirm=true) : "
# Constaté en réel (Proxmox 9, 2026-11-13) : « only root can set 'affinity' config » et « … 'hugepages' config » (comme keyctl / fuse d'un conteneur)
ROOT_ONLY = "Proxmox réserve cette option à root@pam (affinity, hugepages) : elle est refusée au token de Kaji"
PROTECTED = "Machine protégée (KAJI_PROTECTED_VMIDS) : ses options ne se modifient pas depuis Kaji"


class _Ctx:
    def __init__(self, db, factory, user, conn_id, node, gtype, vmid, label):
        self.db, self.factory, self.user, self.conn_id, self.vmid = db, factory, user, conn_id, vmid
        self.path, self.target = f"/nodes/{node}/{gtype}/{vmid}", f"{gtype}/{vmid}@{node}:{label}"

    def log(self, st, detail=None):
        audit.record(self.db, username=self.user.username, connection_id=self.conn_id, action="hw-options", target=self.target, status=st, detail=detail)

    def refuse(self, msg: str, code: int):
        self.log("error", msg)
        raise HTTPException(code, msg)

    async def px(self, method: str, p: str, **kw):
        try:
            return await _px(self.db, self.factory, self.conn_id, method, p, **kw)
        except HTTPException as e:
            if method == "put" and "only root can set" in str(e.detail):
                e = HTTPException(403, ROOT_ONLY)                      # message fixe : ni valeur saisie ni message brut de Proxmox
            self.log("error", str(e.detail))
            raise e

    async def config(self, current: bool = True) -> dict:
        cfg = await self.px("get", f"{self.path}/config", **({"current": 1} if current else {}))
        if not isinstance(cfg, dict):
            self.refuse("Configuration de la machine illisible", 502)
        return cfg

    def guard(self, confirm: bool, risks: list[str]):
        if self.vmid in get_settings().protected_vmids:
            self.refuse(PROTECTED, 409)
        if risks and not confirm:
            self.refuse(CONFIRM + " ; ".join(risks), 400)

    async def write(self, params: dict, delete: list[str], cfg: dict, check, detail: str):
        digest = cfg.get("digest")
        if isinstance(digest, str) and DIGEST.fullmatch(digest):
            params["digest"] = digest                                    # refuse si la configuration a changé entre-temps
        if delete:
            params["delete"] = ",".join(delete)
        await self.px("put", f"{self.path}/config", **params)
        after = await self.config(current=False)                         # relecture : la valeur « en attente » si la machine tourne
        if not check(after):
            self.refuse("Proxmox n'a pas enregistré la modification", 502)
        self.log("started", detail)


def _same(a, b) -> bool:
    """Valeur relue = valeur écrite (Proxmox peut renvoyer 2.0 pour 2 : les nombres se comparent comme des nombres)."""
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a) == str(b)


def _summary(sets: dict, clear: list[str]) -> str:
    return ", ".join([f"{k}={v}" for k, v in sets.items()] + [f"retiré : {','.join(clear)}"] * bool(clear))


@router.patch(B + "/qemu/{vmid}/disks/{key}/options")
async def disk_options(body: DiskOptions, conn_id: int, node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999),
                       key: str = Path(pattern=DISK_KEY.pattern), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                       user: AdminUser = Depends(current_user)):
    """Cache, discard, iothread, ssd, aio, sauvegarde, lecture seule, réplication, limites de débit d'un disque de VM."""
    c = _Ctx(db, factory, user, conn_id, node, "qemu", vmid, key)
    cfg = await c.config()
    if key not in cfg:
        c.refuse("Disque inconnu", 404)
    try:
        new, risks = build_disk(str(cfg[key]), key, body, cfg.get("scsihw"))
    except ValueError as e:
        c.refuse(str(e), 422)
    sets = disk_changes(body)
    if body.dry_run:
        return {"dry_run": True, "options": dict(split_opts(new)[1]), "risks": risks, "protected": vmid in get_settings().protected_vmids}
    c.guard(body.confirm, risks)

    def check(after):
        got = dict(split_opts(str(after.get(key, "")))[1])
        return all(got.get(k) == v for k, v in sets.items()) and not any(k in got for k in body.clear)

    await c.write({key: new}, [], cfg, check, _summary(sets, list(body.clear)))
    return {"disk": key, "options": dict(split_opts(new)[1])}


@router.patch(B + "/{gtype}/{vmid}/nets/{key}/options")
async def net_options(body: NetOptions, conn_id: int, node: str = Path(pattern=NODE), gtype: Literal["qemu", "lxc"] = Path(),
                      vmid: int = Path(ge=100, le=999999999), key: str = Path(pattern=NET_KEY.pattern), db: Session = Depends(get_db),
                      factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Limite de débit, MTU, files multiples, câble débranché, VLAN autorisés (trunks) d'une carte réseau."""
    c = _Ctx(db, factory, user, conn_id, node, gtype, vmid, key)
    cfg = await c.config()
    if key not in cfg:
        c.refuse("Carte réseau inconnue", 404)
    try:
        new, risks = build_net(str(cfg[key]), key, gtype == "lxc", body)
    except ValueError as e:
        c.refuse(str(e), 422)
    if body.dry_run:
        return {"dry_run": True, "options": dict(split_opts(new)[1]), "risks": risks, "protected": vmid in get_settings().protected_vmids}
    c.guard(body.confirm, risks)
    wanted = dict(split_opts(new)[1])
    gone = list(body.clear) + (["link_down"] if body.link_down is False else [])

    def check(after):
        got = dict(split_opts(str(after.get(key, "")))[1])
        return all(got.get(k) == wanted[k] for k in ("rate", "mtu", "queues", "link_down", "trunks") if k in wanted) and not any(k in got for k in gone)

    await c.write({key: new}, [], cfg, check, _summary({k: v for k, v in wanted.items() if k in ("rate", "mtu", "queues", "link_down", "trunks")}, gone))
    return {"net": key, "options": wanted}


@router.patch(B + "/qemu/{vmid}/cpu-options")
async def cpu_options(body: CpuOptions, conn_id: int, node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999),
                      db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Poids CPU (cpuunits), limite (cpulimit), affinité (cœurs du nœud) et hugepages d'une VM."""
    c = _Ctx(db, factory, user, conn_id, node, "qemu", vmid, "cpu")
    cfg = await c.config()
    try:
        status = await _px(db, factory, conn_id, "get", f"/nodes/{node}/status")
        cpus = status.get("cpuinfo", {}).get("cpus") if isinstance(status, dict) else None
        cpus = cpus if isinstance(cpus, int) and cpus > 0 else None
    except HTTPException:
        cpus = None                                                       # illisible : Proxmox validera lui-même
    try:
        sets, clear, risks = build_cpu(body, cpus)
    except ValueError as e:
        c.refuse(str(e), 422)
    if body.dry_run:
        return {"dry_run": True, "params": {k: str(v) for k, v in sets.items()}, "remove": clear, "risks": risks, "protected": vmid in get_settings().protected_vmids}
    c.guard(body.confirm, risks)

    def check(after):
        return all(_same(after.get(k), v) for k, v in sets.items()) and not any(k in after for k in clear)

    await c.write(dict(sets), clear, cfg, check, _summary(sets, clear))
    return {"changed": sorted(sets), "removed": clear}
