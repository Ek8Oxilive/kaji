"""Options d'une VM ou d'un conteneur : démarrage automatique, protection, agent, features… (onglet « Options » de Proxmox).

Lecture et modification par liste blanche (`optionspec.py` pour les VM, `lxcoptionspec.py` pour les LXC). Pas la route `/config` du matériel :
la validation et les risques diffèrent. Un réglage retiré passe par `delete=` (liste blanche, jamais libre). Les réglages dangereux exigent
`confirm`, décidé par le SERVEUR sur l'état relu chez Proxmox ; une machine de `KAJI_PROTECTED_VMIDS` les refuse même confirmés.
RIEN n'a été validé en réel.
"""
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..deps import get_client_factory
from ..lxcoptionspec import (ROOT_ONLY_MESSAGE, LxcOptionsUpdate, build_lxc_params, lxc_protected_refusal, lxc_risks, normalize_lxc_options,
                             touches_root_only)
from ..models import AdminUser
from ..optionspec import DIGEST, OptionsUpdate, build_params, normalize_options, protected_refusal, risks
from .actions import NODE
from .auth import current_user
from .cluster import FORBIDDEN_DETAIL, Factory, _px

router = APIRouter(tags=["options"], dependencies=[Depends(current_user)])
BASE = "/api/connections/{conn_id}/guests/{node}/qemu/{vmid}/options"
LXC_BASE = "/api/connections/{conn_id}/guests/{node}/lxc/{vmid}/options"
CONFIRM = "Confirmation requise (renvoie la requête avec confirm=true) : "


async def _read(conn_id, node, gtype, vmid, db, factory, normalize):
    path = f"/nodes/{node}/{gtype}/{vmid}"
    cfg = await _px(db, factory, conn_id, "get", f"{path}/config", current=1)
    pending = await _px(db, factory, conn_id, "get", f"{path}/pending")
    return normalize(cfg, pending if isinstance(pending, list) else [])


async def _write(gtype, body, build, risk_fn, protected_fn, conn_id, node, vmid, db, factory, user, root_only=None):
    path, target = f"/nodes/{node}/{gtype}/{vmid}", f"{gtype}/{vmid}@{node}"

    def log(st, detail=None):
        audit.record(db, username=user.username, connection_id=conn_id, action="options", target=target, status=st, detail=detail)

    def refuse(msg: str, code: int):
        log("error", msg)
        raise HTTPException(code, msg)

    async def px(method: str, p: str, **kw):
        try:
            return await _px(db, factory, conn_id, method, p, **kw)
        except HTTPException as e:
            if method == "put" and root_only and e.detail == FORBIDDEN_DETAIL and root_only(body, cfg, params, delete):
                e = HTTPException(status.HTTP_403_FORBIDDEN, ROOT_ONLY_MESSAGE)  # message fixe : ni valeur saisie ni message brut de Proxmox
            log("error", str(e.detail))
            raise e

    if not (body.model_fields_set - {"confirm"}):
        refuse("Aucune modification demandée", 400)
    cfg = await px("get", f"{path}/config", current=1)
    if not isinstance(cfg, dict):
        refuse("Configuration de la machine illisible", 502)
    try:
        params, delete = build(body, cfg)
    except ValueError as e:
        refuse(str(e), 422)
    if vmid in get_settings().protected_vmids and (msg := protected_fn(body, cfg)):
        refuse(msg, 409)
    reasons = risk_fn(body, cfg)
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


@router.get(BASE)
async def get_options(conn_id: int, node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999), db: Session = Depends(get_db),
                      factory: Factory = Depends(get_client_factory)):
    """Options actuelles d'une VM, décomposées en champs, avec les changements en attente (`pending`)."""
    return await _read(conn_id, node, "qemu", vmid, db, factory, normalize_options)


@router.patch(BASE, status_code=status.HTTP_200_OK)
async def update_options(body: OptionsUpdate, conn_id: int, node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999),
                         db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _write("qemu", body, build_params, risks, protected_refusal, conn_id, node, vmid, db, factory, user)


@router.get(LXC_BASE)
async def get_lxc_options(conn_id: int, node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999), db: Session = Depends(get_db),
                          factory: Factory = Depends(get_client_factory)):
    """Options actuelles d'un conteneur, décomposées en champs, avec les changements en attente (`pending`)."""
    return await _read(conn_id, node, "lxc", vmid, db, factory, normalize_lxc_options)


@router.patch(LXC_BASE, status_code=status.HTTP_200_OK)
async def update_lxc_options(body: LxcOptionsUpdate, conn_id: int, node: str = Path(pattern=NODE), vmid: int = Path(ge=100, le=999999999),
                             db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """`unprivileged` et `arch` ne sont pas modifiables (422). `keyctl`, `fuse` et `mount` sont réservés à `root@pam` chez Proxmox : son 403 sur
    une demande qui les contient devient un 403 au message explicite (la demande est refusée en entier). Tout autre refus reste un 502 sans fuite."""
    return await _write("lxc", body, build_lxc_params, lxc_risks, lxc_protected_refusal, conn_id, node, vmid, db, factory, user, touches_root_only)
