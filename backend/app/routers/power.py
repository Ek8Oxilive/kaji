"""Alimentation avancée d'une VM (reset, suspendre, hiberner, reprendre) et conversion en modèle (VM et LXC), lot #146.

Les routes `…/qemu/{vmid}/reset|suspend|hibernate|resume` et `…/{type}/{vmid}/template` ont la même forme que la route générique
`{action}` de `actions.py` (`ORDER = 90`) : ce module garde l'ordre par défaut et passe donc avant elle.

L'état de la machine est TOUJOURS relu chez Proxmox au moment de l'action (jamais une valeur du navigateur). Corps : champs inconnus ignorés.
Convertir en modèle est irréversible : machine arrêtée, `confirm=true` ET nom exact retapé, refus si la machine est protégée
(`KAJI_PROTECTED_VMIDS` ou option `protection`) ou déjà un modèle. Chez Proxmox, les disques d'une VM sont renommés `base-…`.
RIEN n'a été validé en réel (lot PC B).
"""
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, StrictBool
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(tags=["power"], dependencies=[Depends(current_user)])
BASE = "/api/connections/{conn_id}/guests/{node}"
STORAGE = re.compile(r"[A-Za-z][A-Za-z0-9._-]{0,63}")        # pve-storage-id
PAUSED = {"paused", "suspended"}                               # `status` / `qmpstatus` d'une VM en pause


class PowerBody(BaseModel):
    confirm: StrictBool = False
    statestorage: str | None = None                            # hibernation seulement : stockage de l'état mémoire


class TemplateBody(BaseModel):
    confirm: StrictBool = False
    name: str = ""


def _states(current) -> tuple[str, str]:
    c = current if isinstance(current, dict) else {}
    return str(c.get("status") or ""), str(c.get("qmpstatus") or "")


async def _do(op: str, gtype: str, body, conn_id, node, vmid, db, factory, user, *, check, params=None, confirm_msg=None, path_suffix=None):
    """Séquence commune : confirmation, état relu, appel Proxmox, audit. Un refus n'émet AUCUNE écriture."""
    target, base = f"{gtype}/{vmid}@{node}", f"/nodes/{node}/{gtype}/{vmid}"

    def log(st, detail=None, upid=None):
        audit.record(db, username=user.username, connection_id=conn_id, action=op, target=target, status=st, detail=detail, upid=upid)

    def refuse(msg, code):
        log("error", msg)
        raise HTTPException(code, msg)

    async def px(method, path, **kw):
        try:
            return await _px(db, factory, conn_id, method, path, **kw)
        except HTTPException as e:
            log("error", str(e.detail))
            raise

    if confirm_msg and not body.confirm:
        refuse(confirm_msg, status.HTTP_400_BAD_REQUEST)
    current = await px("get", f"{base}/status/current")
    if msg := check(*_states(current)):
        refuse(msg, status.HTTP_409_CONFLICT)
    upid = await px("post", f"{base}/{path_suffix or f'status/{op}'}", **(params or {}))
    log("started", None, upid if isinstance(upid, str) else None)
    return {"upid": upid if isinstance(upid, str) else None, "node": node, "action": op}


def _running(verb):
    return lambda st, qmp: None if st == "running" and qmp not in PAUSED | {"prelaunch"} else f"La VM doit être en marche (et non en pause) pour {verb}"


async def _power(op, check, body, conn_id, node, vmid, db, factory, user, *, confirm_msg=None, params=None, path_suffix=None):
    return await _do(op, "qemu", body or PowerBody(), conn_id, node, vmid, db, factory, user, check=check, confirm_msg=confirm_msg, params=params,
                     path_suffix=path_suffix)


Q = dict(status_code=status.HTTP_202_ACCEPTED)


@router.get(BASE + "/qemu/{vmid}/power")
async def vm_power_state(conn_id: int, node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999),
                         db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """État d'alimentation relu chez Proxmox (la liste des machines ne dit pas « en pause ») : `status`, `qmpstatus`, `paused`."""
    st, qmp = _states(await _px(db, factory, conn_id, "get", f"/nodes/{node}/qemu/{vmid}/status/current"))
    return {"status": st or None, "qmpstatus": qmp or None, "paused": bool({st, qmp} & PAUSED)}


@router.post(BASE + "/qemu/{vmid}/reset", **Q)
async def reset_vm(conn_id: int, body: PowerBody | None = None, node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999),
                   db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Coupure brutale puis redémarrage (comme le bouton reset). Exige `confirm` : les données non enregistrées sont perdues."""
    return await _power("reset", _running("être réinitialisée"), body, conn_id, node, vmid, db, factory, user,
                        confirm_msg="« reset » coupe brutalement la VM : renvoie la requête avec {\"confirm\": true}")


@router.post(BASE + "/qemu/{vmid}/suspend", **Q)
async def suspend_vm(conn_id: int, body: PowerBody | None = None, node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999),
                     db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Suspend la VM en mémoire (elle reste « paused » jusqu'à `resume`)."""
    return await _power("suspend", _running("être suspendue"), body, conn_id, node, vmid, db, factory, user)


@router.post(BASE + "/qemu/{vmid}/hibernate", **Q)
async def hibernate_vm(conn_id: int, body: PowerBody | None = None, node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999),
                       db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Hiberne sur disque (`suspend` avec `todisk=1`) ; reprise au prochain démarrage. Exige `confirm` (agent invité conseillé)."""
    body = body or PowerBody()
    if body.statestorage is not None and not STORAGE.fullmatch(body.statestorage):
        audit.record(db, username=user.username, connection_id=conn_id, action="hibernate", target=f"qemu/{vmid}@{node}", status="error",
                     detail="stockage d'état invalide")
        raise HTTPException(422, "Stockage d'état invalide")
    params = {"todisk": 1, **({"statestorage": body.statestorage} if body.statestorage else {})}
    return await _power("hibernate", _running("être hibernée"), body, conn_id, node, vmid, db, factory, user, params=params,
                        confirm_msg="« hibernate » écrit la mémoire sur disque et arrête la VM : renvoie la requête avec {\"confirm\": true}",
                        path_suffix="status/suspend")


@router.post(BASE + "/qemu/{vmid}/resume", **Q)
async def resume_vm(conn_id: int, body: PowerBody | None = None, node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999),
                    db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Reprend une VM en pause (état « paused » ou « suspended » relu chez Proxmox). Une VM hibernée sur disque se démarre."""
    return await _power("resume", lambda st, qmp: None if {st, qmp} & PAUSED else "La VM n'est pas en pause : rien à reprendre",
                        body, conn_id, node, vmid, db, factory, user)


@router.post(BASE + "/{gtype}/{vmid}/template", **Q)
async def convert_to_template(conn_id: int, body: TemplateBody | None = None, node: str = Path(pattern=NODE),
                              gtype: Literal["qemu", "lxc"] = Path(), vmid: int = Path(ge=100, le=999999999),
                              db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                              user: AdminUser = Depends(current_user)):
    """Convertit en modèle, IRRÉVERSIBLE (les disques d'une VM deviennent `base-…`). Exige : machine arrêtée, `confirm=true`, nom exact retapé,
    ni protégée (Kaji ou option `protection`) ni déjà un modèle."""
    body = body or TemplateBody()
    target, base = f"{gtype}/{vmid}@{node}", f"/nodes/{node}/{gtype}/{vmid}"

    def log(st, detail=None, upid=None):
        audit.record(db, username=user.username, connection_id=conn_id, action="guest-template", target=target, status=st, detail=detail, upid=upid)

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
        refuse(f"La machine #{vmid} est protégée par Kaji (KAJI_PROTECTED_VMIDS) : conversion impossible", 403)
    if not body.confirm:
        refuse("Conversion irréversible en modèle : renvoie la requête avec confirm=true et le nom de la machine (name)", 400)
    current = await px("get", f"{base}/status/current")
    if (current or {}).get("status") != "stopped":
        refuse("La machine doit être arrêtée avant d'être convertie en modèle", 409)
    cfg = await px("get", f"{base}/config", current=1)
    if not isinstance(cfg, dict):
        refuse("Configuration de la machine illisible", 502)
    if str(cfg.get("template")) == "1":
        refuse("La machine est déjà un modèle", 409)
    if str(cfg.get("protection")) == "1":
        refuse("La machine est protégée dans Proxmox (option « protection ») : désactive-la d'abord", 409)
    machine = cfg.get("hostname" if gtype == "lxc" else "name")
    if not machine or body.name != machine:
        refuse("Le nom de la machine ne correspond pas : conversion refusée", 400)
    upid = await px("post", f"{base}/template")
    log("started", f"« {machine} » convertie en modèle (irréversible)", upid if isinstance(upid, str) else None)
    return {"upid": upid if isinstance(upid, str) else None, "node": node, "action": "template"}
