"""Options d'une VM : démarrage automatique, protection, agent, hotplug… (onglet « Options » de Proxmox).

Lecture et modification par liste blanche (`optionspec.py`). Pas la route `/config` du matériel : la validation et les risques diffèrent.
Un réglage retiré passe par `delete=` (liste blanche, jamais libre). Les réglages dangereux exigent `confirm`, décidé par le SERVEUR sur
l'état relu chez Proxmox ; une machine de `KAJI_PROTECTED_VMIDS` les refuse même confirmés. RIEN n'a été validé en réel.
"""
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..optionspec import DIGEST, OptionsUpdate, build_params, normalize_options, protected_refusal, risks
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(tags=["options"], dependencies=[Depends(current_user)])
BASE = "/api/connections/{conn_id}/guests/{node}/qemu/{vmid}/options"
CONFIRM = "Confirmation requise (renvoie la requête avec confirm=true) : "


@router.get(BASE)
async def get_options(conn_id: int, node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999), db: Session = Depends(get_db),
                      factory: Factory = Depends(get_client_factory)):
    """Options actuelles d'une VM, décomposées en champs, avec les changements en attente (`pending`)."""
    path = f"/nodes/{node}/qemu/{vmid}"
    cfg = await _px(db, factory, conn_id, "get", f"{path}/config", current=1)
    pending = await _px(db, factory, conn_id, "get", f"{path}/pending")
    return normalize_options(cfg, pending if isinstance(pending, list) else [])


@router.patch(BASE, status_code=status.HTTP_200_OK)
async def update_options(body: OptionsUpdate, conn_id: int, node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999),
                         db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    path, target = f"/nodes/{node}/qemu/{vmid}", f"qemu/{vmid}@{node}"

    def log(st, detail=None):
        audit.record(db, username=user.username, connection_id=conn_id, action="options", target=target, status=st, detail=detail)

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
    cfg = await px("get", f"{path}/config", current=1)
    if not isinstance(cfg, dict):
        refuse("Configuration de la machine illisible", 502)
    try:
        params, delete = build_params(body, cfg)
    except ValueError as e:
        refuse(str(e), 422)
    if vmid in get_settings().protected_vmids and (msg := protected_refusal(body, cfg)):
        refuse(msg, 409)
    reasons = risks(body, cfg)
    if reasons and not body.confirm:
        refuse(CONFIRM + " ; ".join(reasons), 400)
    digest = cfg.get("digest")
    if isinstance(digest, str) and DIGEST.fullmatch(digest):
        params["digest"] = digest                                         # refuse si la configuration a changé entre-temps
    if delete:
        params["delete"] = ",".join(delete)
    await px("put", f"{path}/config", **params)
    shown = [k if k == "description" else f"{k}={v}" for k, v in params.items() if k not in ("digest", "delete")]
    log("started", ", ".join(shown + [f"retiré : {','.join(delete)}"] * bool(delete)))
    return {"changed": sorted(k for k in params if k not in ("digest", "delete")), "removed": delete}
