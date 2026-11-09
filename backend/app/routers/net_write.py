"""Réseau d'un nœud en écriture : préparer (en attente), appliquer, annuler. Validation et verrous : `app/networkwrite.py`."""
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..fwoptions import PHRASE
from ..models import AdminUser
from ..networkspec import shape_network
from ..networkwrite import (CLEARABLE, FIELDS, KINDS, Locks, NetCreate, NetUpdate, NAME, apply_locks, check_consistency, check_name, management_ifaces, params_of,
                            stage_locks)
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}/nodes/{node}/network", tags=["network-write"], dependencies=[Depends(current_user)])
IFACE_P = Path(pattern=NAME.pattern)


class Ctx:
    def __init__(self, db, factory, user, conn_id, node, action, target):
        self.db, self.factory, self.user, self.conn_id, self.node, self.action, self.target = db, factory, user, conn_id, node, action, target

    def log(self, st, detail=None):
        audit.record(self.db, username=self.user.username, connection_id=self.conn_id, action=self.action, target=self.target, status=st, detail=detail)

    def refuse(self, msg, code):
        self.log("error", msg)
        raise HTTPException(code, msg)

    async def px(self, method, path, /, **kw):
        try:
            return await _px(self.db, self.factory, self.conn_id, method, path, **kw)
        except HTTPException as e:
            self.log("error", str(e.detail))
            raise

    async def state(self):
        return shape_network(await self.px("get_envelope", f"/nodes/{self.node}/network"))

    def gate(self, body: Locks, lk: dict):
        """Dry-run ou verrous : renvoie la réponse de dry_run, ou None si on peut écrire ; refuse (409) sinon."""
        if body.dry_run:
            return {"dry_run": True, "locks": lk, "phrase": PHRASE if lk["cut"] else None}
        if not body.confirm:
            self.refuse("Écriture réseau : renvoie la requête avec confirm=true (ou dry_run=true pour voir les verrous)", 400)
        if lk["cut"]:
            if not (body.acknowledge_cut_access and body.type_name == PHRASE):
                self.refuse("Coupure d'accès possible : " + " ; ".join(lk["cut"]) + f". Renvoie la requête avec acknowledge_cut_access=true et type_name=\"{PHRASE}\"", status.HTTP_409_CONFLICT)
        elif lk["live"] and not body.acknowledge_live:
            self.refuse("Réseau actif : " + " ; ".join(lk["live"]) + ". Renvoie la requête avec acknowledge_live=true pour confirmer", status.HTTP_409_CONFLICT)
        return None


def _cfg(i: dict | None) -> dict:
    return {k: v for k, v in (i or {}).items() if k in FIELDS and v not in (None, [], "")}


def _same(want: dict, got: dict) -> bool:
    return all(got.get(k) == v for k, v in want.items() if k in ("cidr", "cidr6", "gateway", "gateway6", "mtu", "comments", "bridge_ports", "slaves", "bridge_vlan_aware", "bond_mode"))


async def _stage(op: str, ctx: Ctx, name: str, body, kind: str | None):
    st = await ctx.state()
    ifaces = st["interfaces"]
    by = {i["iface"]: i for i in ifaces}
    cur = by.get(name)
    change = {k: getattr(body, k) for k in body.model_fields_set if k in FIELDS and getattr(body, k) is not None}
    clear = list(getattr(body, "clear", []))
    if op == "create":
        if cur is not None:
            ctx.refuse("Cette interface existe déjà", status.HTTP_409_CONFLICT)
    else:
        if cur is None:
            ctx.refuse("Interface inconnue", status.HTTP_404_NOT_FOUND)
        if cur["type"] not in KINDS:
            ctx.refuse("Ce type d'interface n'est pas géré par Kaji (Open vSwitch, fabric, VNet…)", 422)
        kind = cur["type"]
    new = None
    if op != "delete":
        if op == "update":
            bad = [k for k in clear if k not in CLEARABLE]
            if bad or set(clear) & set(change):
                ctx.refuse("Champ non retirable, ou à la fois modifié et retiré", 422)
            if not change and not clear:
                ctx.refuse("Aucune modification demandée", 422)
        new = {**_cfg(cur), **change} if op == "update" else dict(change)
        for k in clear:
            new.pop(k, None)
        try:
            if op == "create":
                check_name(kind, name, None)
            check_consistency(kind, name, new, {k: v for k, v in by.items() if k != name})
        except ValueError as e:
            ctx.refuse(str(e), 422)
    else:
        users = sorted(o for o, i in by.items() if o != name and (name in i["bridge_ports"] or name in i["slaves"] or i.get("vlan_raw_device") == name))
        if users:
            ctx.refuse(f"Utilisée par {', '.join(users)} : retire-la d'abord de leurs ports", status.HTTP_409_CONFLICT)
    mgmt = management_ifaces(ifaces)
    other_gw = any(i["has_gateway"] and n != name for n, i in by.items())
    lk = stage_locks(name, op, change, mgmt, other_gw)
    params: dict = {}
    if op == "create":
        params = {"type": kind, "iface": name, **params_of(change)}
    elif op == "update":
        params = {"type": kind, **params_of(change)}
        if clear:
            params["delete"] = ",".join({"bond_primary": "bond-primary"}.get(k, k) for k in clear)
    if (r := ctx.gate(body, lk)) is not None:
        return {**r, "params": params, "pending": st["pending"]}
    base = f"/nodes/{ctx.node}/network"
    if op == "create":
        await ctx.px("post", base, **params)
    elif op == "update":
        await ctx.px("put", f"{base}/{name}", **params)
    else:
        await ctx.px("delete", f"{base}/{name}")
    after = await ctx.state()
    row = next((i for i in after["interfaces"] if i["iface"] == name), None)
    ok = (row is None) if op == "delete" else (row is not None and _same(new, _cfg(row)) and (op == "update" or row["type"] == kind))
    if not ok or not after["pending"]:
        ctx.refuse("Proxmox n'a pas enregistré la modification", status.HTTP_502_BAD_GATEWAY)
    ctx.log("started", f"{op} {kind or ''} {name} (en attente, non appliquée)")
    return {"staged": True, "applied": False, "pending": True, "locks": lk, "changes": after["changes"]}


@router.post("/interfaces")
async def create_iface(body: NetCreate, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                       user: AdminUser = Depends(current_user)):
    return await _stage("create", Ctx(db, factory, user, conn_id, node, "net-create", f"{node}:{body.iface}"), body.iface, body, body.type)


@router.put("/interfaces/{iface}")
async def update_iface(body: NetUpdate, conn_id: int, node: str = Path(pattern=NODE), iface: str = IFACE_P, db: Session = Depends(get_db),
                       factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _stage("update", Ctx(db, factory, user, conn_id, node, "net-update", f"{node}:{iface}"), iface, body, None)


@router.delete("/interfaces/{iface}")
async def delete_iface(conn_id: int, node: str = Path(pattern=NODE), iface: str = IFACE_P, confirm: bool = Query(default=False),
                       acknowledge_cut_access: bool = Query(default=False), type_name: str | None = Query(default=None, max_length=40), dry_run: bool = Query(default=False),
                       db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    body = Locks(confirm=confirm, acknowledge_cut_access=acknowledge_cut_access, type_name=type_name, dry_run=dry_run)
    return await _stage("delete", Ctx(db, factory, user, conn_id, node, "net-delete", f"{node}:{iface}"), iface, body, None)


@router.post("/apply")
async def apply(body: Locks, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                user: AdminUser = Depends(current_user)):
    """Applique les modifications en attente : recharge le réseau du nœud. Jamais de retour arrière automatique."""
    ctx = Ctx(db, factory, user, conn_id, node, "net-apply", node)
    st = await ctx.state()
    if not st["pending"]:
        ctx.refuse("Aucune modification en attente", status.HTTP_409_CONFLICT)
    lk = apply_locks(st["changes"], management_ifaces(st["interfaces"]))
    if (r := ctx.gate(body, lk)) is not None:
        return {**r, "changes": st["changes"]}
    upid = await ctx.px("put", f"/nodes/{node}/network")
    ctx.log("started", "modifications appliquées (rechargement du réseau)" + (" ; touche l'interface d'administration" if lk["cut"] else ""))
    return {"applied": True, "task": upid if isinstance(upid, str) and len(upid) < 300 else None, "locks": lk}


@router.post("/revert")
async def revert(body: Locks, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                 user: AdminUser = Depends(current_user)):
    """Annule toutes les modifications en attente (inerte : rien n'avait été appliqué)."""
    ctx = Ctx(db, factory, user, conn_id, node, "net-revert", node)
    st = await ctx.state()
    if not st["pending"]:
        ctx.refuse("Aucune modification en attente", status.HTTP_409_CONFLICT)
    lk = {"cut": [], "live": [], "inert": True}
    if (r := ctx.gate(body, lk)) is not None:
        return {**r, "changes": st["changes"]}
    await ctx.px("delete", f"/nodes/{node}/network")
    if (await ctx.state())["pending"]:
        ctx.refuse("Proxmox n'a pas annulé les modifications", status.HTTP_502_BAD_GATEWAY)
    ctx.log("started", "modifications en attente annulées")
    return {"reverted": True}
