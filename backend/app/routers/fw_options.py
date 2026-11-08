"""Options du pare-feu (datacenter, nœud, machine) : écrire, avec verrous à déverrouillage explicite et mode `dry_run`. Verrous : `app/fwoptions.py`."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..deps import get_client_factory
from ..fwoptions import PHRASE, ClusterOptions, GuestOptions, NodeOptions, build, locks
from ..models import AdminUser
from ..networkspec import shape_options
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}/firewall", tags=["firewall-write"], dependencies=[Depends(current_user)])


async def _apply(level: str, label: str, base: str, body, conn_id: int, db: Session, factory: Factory, user: AdminUser, protected_guest: bool = False):
    def log(st, detail=None):
        audit.record(db, username=user.username, connection_id=conn_id, action="fw-options", target=label, status=st, detail=detail)

    def refuse(msg: str, code: int):
        log("error", msg)
        raise HTTPException(code, msg)

    async def px(method, path, /, **kw):
        try:
            return await _px(db, factory, conn_id, method, path, **kw)
        except HTTPException as e:
            log("error", str(e.detail))
            raise

    if not body.dry_run and not body.confirm:
        refuse("Écriture dans le pare-feu : renvoie la requête avec confirm=true (ou dry_run=true pour voir les verrous)", 400)
    try:
        params, delete = build(level, body)
    except ValueError as e:
        refuse(str(e), 422)
    raw = await px("get", f"{base}/options")
    cur = shape_options(level, raw)
    lk = locks(level, cur, params, delete, protected_guest)
    if body.dry_run:
        return {"dry_run": True, "params": params, "remove": delete, "locks": lk, "phrase": PHRASE if lk["cut"] else None}
    if lk["cut"]:
        if not (body.acknowledge_cut_access and body.type_name == PHRASE):
            refuse("Coupure d'accès possible : " + " ; ".join(lk["cut"]) + f". Renvoie la requête avec acknowledge_cut_access=true et type_name=\"{PHRASE}\"", status.HTTP_409_CONFLICT)
    elif lk["live"] and not body.acknowledge_live:
        refuse("Pare-feu actif : " + " ; ".join(lk["live"]) + ". Renvoie la requête avec acknowledge_live=true pour confirmer", status.HTTP_409_CONFLICT)
    send = dict(params)
    if delete:
        send["delete"] = ",".join(delete)
    if isinstance(cur.get("digest"), str):
        send["digest"] = cur["digest"]                                    # refus si la configuration a changé entre-temps
    await px("put", f"{base}/options", **send)
    after = shape_options(level, await px("get", f"{base}/options"))
    for k, v in params.items():
        want = bool(v) if k in ("enable", "ebtables", "log_nf_conntrack", "ndp", "nf_conntrack_allow_invalid", "nftables", "nosmurfs", "protection_synflood", "tcpflags", "dhcp",
                                "ipfilter", "macfilter", "radv") else v
        if after.get(k) != want:
            refuse("Proxmox n'a pas appliqué la modification", status.HTTP_502_BAD_GATEWAY)
    log("started", ", ".join(f"{k}={v}" for k, v in sorted(params.items())) + (f" ; retiré : {','.join(delete)}" if delete else "")
        + (" ; niveau inactif : appliqué à l'activation" if lk["inert"] and not cur.get("enable") else ""))
    return {"changed": sorted(params), "removed": delete, "locks": lk, "inactive_level": bool(lk["inert"] and not (params.get("enable") or cur.get("enable")))}


@router.put("/cluster/options")
async def cluster_options(body: ClusterOptions, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _apply("cluster", "datacenter", "/cluster/firewall", body, conn_id, db, factory, user)


@router.put("/nodes/{node}/options")
async def node_options(body: NodeOptions, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                       user: AdminUser = Depends(current_user)):
    return await _apply("node", f"node:{node}", f"/nodes/{node}/firewall", body, conn_id, db, factory, user)


@router.put("/guests/{node}/{gtype}/{vmid}/options")
async def guest_options(body: GuestOptions, conn_id: int, node: str = Path(pattern=NODE), gtype: Literal["qemu", "lxc"] = Path(), vmid: int = Path(ge=100, le=999999999),
                        db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _apply("guest", f"{gtype}/{vmid}@{node}", f"/nodes/{node}/{gtype}/{vmid}/firewall", body, conn_id, db, factory, user, protected_guest=vmid in get_settings().protected_vmids)
