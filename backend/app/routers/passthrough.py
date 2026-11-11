"""Passthrough PCI, USB et répertoires d'une VM par CORRESPONDANCE (onglet Matériel) : lire, ajouter, modifier, retirer. Validation et formats : `app/passthroughspec.py`.

Droits Proxmox : `VM.Config.HWType` sur la VM et `Mapping.Use` sur la correspondance. Les périphériques « bruts » (`host=…`, réservés à `root@pam`) sont montrés en lecture seule : Kaji ne les crée,
ne les modifie ni ne les retire jamais. Une VM de `KAJI_PROTECTED_VMIDS` est refusée. Rien n'est appliqué à chaud : si la VM tourne, le changement reste « en attente » jusqu'à son arrêt complet.
"""
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..deps import get_client_factory
from ..mappingspec import shape_list
from ..models import AdminUser
from ..passthroughspec import KEY, MAPKEY, PREFIX, Device, PType, build, free_key, parse, shape_devices
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}/guests/{node}/qemu/{vmid}/passthrough", tags=["passthrough"], dependencies=[Depends(current_user)])


class Ctx:
    def __init__(self, db: Session, factory: Factory, conn_id: int, user: AdminUser, node: str, vmid: int, action: str):
        self.db, self.factory, self.conn_id, self.user, self.action = db, factory, conn_id, user, action
        self.path, self.target = f"/nodes/{node}/qemu/{vmid}", f"qemu/{vmid}@{node}"
        self.node, self.vmid = node, vmid

    def log(self, st: str, detail: str | None = None):
        audit.record(self.db, username=self.user.username, connection_id=self.conn_id, action=self.action, target=self.target, status=st, detail=detail)

    def refuse(self, msg: str, code: int):
        self.log("error", msg)
        raise HTTPException(code, msg)

    async def px(self, method: str, path: str, /, **kw):
        try:
            return await _px(self.db, self.factory, self.conn_id, method, path, **kw)
        except HTTPException as e:
            self.log("error", str(e.detail))
            raise

    def forbid_protected(self):
        if self.vmid in get_settings().protected_vmids:
            self.refuse("Machine protégée (KAJI_PROTECTED_VMIDS) : ses périphériques ne se modifient pas depuis Kaji, même confirmé", status.HTTP_403_FORBIDDEN)


async def _config(c: Ctx) -> dict:
    cfg = await c.px("get", f"{c.path}/config")                        # sans `current` : configuration fusionnée avec les changements en attente
    return cfg if isinstance(cfg, dict) else {}


async def _running(c: Ctx) -> bool | None:
    st = await c.px("get", f"{c.path}/status/current")
    return None if not isinstance(st, dict) else st.get("status") == "running"


@router.get("")
async def get_passthrough(conn_id: int, node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Périphériques PCI, USB et répertoires de la VM, les changements en attente et l'état de la machine. Lecture seule."""
    async def px(path, **kw):
        return await _px(db, factory, conn_id, "get", path, **kw)
    base = f"/nodes/{node}/qemu/{vmid}"
    cfg = await px(f"{base}/config")                                  # fusionnée avec les changements en attente (ce que la machine aura après un arrêt complet)
    st = await px(f"{base}/status/current")
    pend = await px(f"{base}/pending")
    pending = sorted({r["key"] for r in (pend if isinstance(pend, list) else []) if isinstance(r, dict) and isinstance(r.get("key"), str) and ("pending" in r or "delete" in r)
                      and any(KEY[t].fullmatch(r["key"]) for t in KEY)})
    machine = cfg.get("machine") if isinstance(cfg, dict) and isinstance(cfg.get("machine"), str) and len(cfg["machine"]) <= 60 else None
    return {"pci": shape_devices(cfg, "pci"), "usb": shape_devices(cfg, "usb"), "dir": shape_devices(cfg, "dir"), "pending": pending, "machine": machine,
            "running": (st.get("status") == "running") if isinstance(st, dict) else None}


async def _prepare(c: Ctx, ptype: str, body: Device, key: str | None):
    """Contrôles communs à l'ajout et à la modification. Renvoie `(config, clé, valeur, avertissements, mapping)`."""
    c.forbid_protected()
    try:
        value = build(ptype, body)
    except ValueError as e:
        c.refuse(str(e), status.HTTP_422_UNPROCESSABLE_ENTITY)
    cfg = await _config(c)
    if key is None:
        key = free_key(cfg, ptype)
        if key is None:
            c.refuse("Plus d'emplacement libre pour ce type de périphérique", status.HTTP_409_CONFLICT)
    else:
        cur = parse(ptype, key, cfg.get(key))
        if cur is None:
            c.refuse("Périphérique introuvable", status.HTTP_404_NOT_FOUND)
        if cur["raw"]:
            c.refuse("Périphérique brut (hôte) : réservé à root@pam, Kaji ne le modifie pas", status.HTTP_409_CONFLICT)
        if cur["other"]:
            c.refuse(f"Ce périphérique porte des options que Kaji ne gère pas ({', '.join(cur['other'])}) : un remplacement les perdrait, modifie-le dans Proxmox", status.HTTP_409_CONFLICT)
    mapping = next((m for m in shape_list(await c.px("get", f"/cluster/mapping/{ptype}"), ptype) if m["id"] == body.mapping), None)
    if mapping is None:
        c.refuse("Correspondance introuvable (crée-la d'abord dans la page Datacenter)", status.HTTP_422_UNPROCESSABLE_ENTITY)
    twin = next((r["key"] for r in shape_devices(cfg, ptype) if r["mapping"] == body.mapping and r["key"] != key), None)
    if twin:
        c.refuse(f"Cette correspondance est déjà utilisée par {twin}", status.HTTP_409_CONFLICT)
    if ptype == "pci" and body.mdev and not mapping["mdev"]:
        c.refuse("Cette correspondance n'est pas marquée « médiée » (mdev) : modifie-la d'abord", status.HTTP_422_UNPROCESSABLE_ENTITY)
    warnings = []
    if not any(e["node"] == c.node for e in mapping["map"]):
        warnings.append(f"La correspondance n'a aucune entrée pour le nœud {c.node} : la machine ne pourra pas démarrer ici")
    if ptype == "pci" and body.pcie and not str(cfg.get("machine", "")).startswith("q35"):
        warnings.append("pcie=1 demande le type de machine q35")
    return cfg, key, value, warnings, mapping


def _digest(cfg: dict) -> dict:
    d = cfg.get("digest")
    return {"digest": d} if isinstance(d, str) and len(d) <= 64 and d.isalnum() else {}


async def _write(c: Ctx, ptype: str, key: str, value: str, cfg: dict, response: Response | None, creating: bool):
    running = await _running(c)
    await c.px("put", f"{c.path}/config", **{key: value}, **_digest(cfg))
    after = parse(ptype, key, (await _config(c)).get(key))
    if after is None or after["raw"] or parse(ptype, key, value) != after:
        c.refuse("Proxmox n'a pas appliqué la modification", status.HTTP_502_BAD_GATEWAY)
    c.log("started", f"{key} : {MAPKEY[ptype]}={after['mapping']}" + (" (en attente : la machine tourne)" if running else ""))
    if response is not None and creating:
        response.status_code = status.HTTP_201_CREATED
    return {"key": key, "device": after, "pending": bool(running)}


@router.post("/{ptype}", status_code=status.HTTP_201_CREATED)
async def add_device(body: Device, response: Response, conn_id: int, ptype: PType = Path(), node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999), db: Session = Depends(get_db),
                     factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Ajoute un périphérique par correspondance dans le premier emplacement libre."""
    c = Ctx(db, factory, conn_id, user, node, vmid, "passthrough-add")
    cfg, key, value, warnings, _ = await _prepare(c, ptype, body, None)
    if body.dry_run:
        response.status_code = status.HTTP_200_OK
        return {"dry_run": True, "key": key, "value": value, "warnings": warnings, "running": await _running(c)}
    out = await _write(c, ptype, key, value, cfg, response, True)
    return {**out, "warnings": warnings}


@router.put("/{ptype}/{key}")
async def update_device(body: Device, conn_id: int, ptype: PType = Path(), key: str = Path(max_length=12), node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999),
                        db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Remplace un périphérique existant (correspondance et options : tout ce qui n'est pas donné est retiré)."""
    c = Ctx(db, factory, conn_id, user, node, vmid, "passthrough-update")
    if not KEY[ptype].fullmatch(key):
        c.refuse("Emplacement invalide", status.HTTP_404_NOT_FOUND)
    cfg, key, value, warnings, _ = await _prepare(c, ptype, body, key)
    if body.dry_run:
        return {"dry_run": True, "key": key, "value": value, "warnings": warnings, "running": await _running(c)}
    out = await _write(c, ptype, key, value, cfg, None, False)
    return {**out, "warnings": warnings}


@router.delete("/{ptype}/{key}")
async def remove_device(conn_id: int, ptype: PType = Path(), key: str = Path(max_length=12), node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999), confirm: bool = Query(default=False),
                        dry_run: bool = Query(default=False), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Retire un périphérique par correspondance de la configuration (exige `confirm=true`)."""
    c = Ctx(db, factory, conn_id, user, node, vmid, "passthrough-remove")
    c.forbid_protected()
    if not KEY[ptype].fullmatch(key):
        c.refuse("Emplacement invalide", status.HTTP_404_NOT_FOUND)
    cfg = await _config(c)
    cur = parse(ptype, key, cfg.get(key))
    if cur is None:
        c.refuse("Périphérique introuvable", status.HTTP_404_NOT_FOUND)
    if cur["raw"]:
        c.refuse("Périphérique brut (hôte) : réservé à root@pam, Kaji ne le retire pas", status.HTTP_409_CONFLICT)
    running = await _running(c)
    if dry_run:
        return {"dry_run": True, "remove": key, "mapping": cur["mapping"], "running": running}
    if not confirm:
        c.refuse("Retrait : renvoie la requête avec confirm=true", status.HTTP_400_BAD_REQUEST)
    await c.px("put", f"{c.path}/config", delete=key, **_digest(cfg))
    if parse(ptype, key, (await _config(c)).get(key)) is not None:
        c.refuse("Proxmox n'a pas retiré le périphérique", status.HTTP_502_BAD_GATEWAY)
    c.log("started", f"{key} retiré (mapping={cur['mapping']})" + (" (en attente : la machine tourne)" if running else ""))
    return {"removed": key, "pending": bool(running)}
