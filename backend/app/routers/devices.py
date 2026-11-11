"""Périphériques d'une VM : carte d'affichage, ports série (socket), audio, RNG, watchdog (lot #225).

Lecture et modification par liste blanche (`devicespec.py`). Un port série n'est jamais un périphérique de l'hôte et le RNG ne lit que
`/dev/urandom`. `confirm` est décidé par le SERVEUR sur l'état relu chez Proxmox (console graphique perdue). Une machine de
`KAJI_PROTECTED_VMIDS` refuse toute modification. Les changements s'appliquent au prochain démarrage (relu via `pending`).
RIEN n'a été validé en réel (lot PC B).
"""
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..deps import get_client_factory
from ..devicespec import DevicesUpdate, build_params, normalize_devices, risks
from ..models import AdminUser
from ..optionspec import DIGEST
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(tags=["devices"], dependencies=[Depends(current_user)])
BASE = "/api/connections/{conn_id}/guests/{node}/qemu/{vmid}/devices"
CONFIRM = "Confirmation requise (renvoie la requête avec confirm=true) : "


@router.get(BASE)
async def get_devices(conn_id: int, node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999), db: Session = Depends(get_db),
                      factory: Factory = Depends(get_client_factory)):
    """Périphériques actuels d'une VM, décomposés en champs, avec les changements en attente (`pending`)."""
    path = f"/nodes/{node}/qemu/{vmid}"
    cfg = await _px(db, factory, conn_id, "get", f"{path}/config", current=1)
    pending = await _px(db, factory, conn_id, "get", f"{path}/pending")
    return normalize_devices(cfg, pending if isinstance(pending, list) else [])


@router.patch(BASE, status_code=status.HTTP_200_OK)
async def update_devices(body: DevicesUpdate, conn_id: int, node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999),
                         db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    path, target = f"/nodes/{node}/qemu/{vmid}", f"qemu/{vmid}@{node}"

    def log(st, detail=None):
        audit.record(db, username=user.username, connection_id=conn_id, action="devices", target=target, status=st, detail=detail)

    def refuse(msg: str, code: int):
        log("error", msg)
        raise HTTPException(code, msg)

    async def px(method: str, p: str, **kw):
        try:
            return await _px(db, factory, conn_id, method, p, **kw)
        except HTTPException as e:
            log("error", str(e.detail))
            raise

    if not (body.model_fields_set - {"confirm"}):
        refuse("Aucune modification demandée", 400)
    if vmid in get_settings().protected_vmids:
        refuse(f"La machine #{vmid} est protégée par Kaji (KAJI_PROTECTED_VMIDS) : modification refusée", 409)
    cfg = await px("get", f"{path}/config", current=1)
    if not isinstance(cfg, dict):
        refuse("Configuration de la machine illisible", 502)
    try:
        params, delete = build_params(body, cfg)
    except ValueError as e:
        refuse(str(e), 422)
    reasons = risks(body, cfg)
    if reasons and not body.confirm:
        refuse(CONFIRM + " ; ".join(reasons), 400)
    digest = cfg.get("digest")
    if isinstance(digest, str) and DIGEST.fullmatch(digest):
        params["digest"] = digest                                         # refuse si la configuration a changé entre-temps
    if delete:
        params["delete"] = ",".join(delete)
    await px("put", f"{path}/config", **params)
    shown = [f"{k}={v}" for k, v in params.items() if k not in ("digest", "delete")]
    log("started", ", ".join(shown + [f"retiré : {','.join(delete)}"] * bool(delete)))
    return {"changed": sorted(k for k in params if k not in ("digest", "delete")), "removed": delete}
