"""SDN (zones, VNets, sous-réseaux) : lecture et écriture en attente, appliquer, annuler. Validation et verrous : `app/sdnspec.py`."""
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..fwoptions import PHRASE
from ..models import AdminUser
from ..sdnspec import (SUBNET_FIELDS, SUBNET_ID, VNET_FIELDS, VNET_ID, ZONE_FIELDS, ZONE_ID, Locks, SubnetCreate, SubnetUpdate, VnetCreate, VnetUpdate, ZoneCreate, ZoneUpdate,
                       apply_locks, check_subnet, check_zone, params_of, shape_subnets, shape_vnets, shape_zones, subnet_id, wire)
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}/sdn", tags=["sdn"], dependencies=[Depends(current_user)])
ZONE_P, VNET_P, SUBNET_P = Path(pattern=ZONE_ID.pattern), Path(pattern=VNET_ID.pattern), Path(pattern=SUBNET_ID.pattern)


class Ctx:
    def __init__(self, db, factory, user, conn_id, action, target):
        self.db, self.factory, self.user, self.conn_id, self.action, self.target = db, factory, user, conn_id, action, target

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

    def gate(self, body: Locks, lk: dict, extra: dict):
        if body.dry_run:
            return {"dry_run": True, "locks": lk, "phrase": PHRASE if lk["cut"] else None, **extra}
        if not body.confirm:
            self.refuse("Écriture SDN : renvoie la requête avec confirm=true (ou dry_run=true pour voir les verrous)", 400)
        if lk["cut"]:
            if not (body.acknowledge_cut_access and body.type_name == PHRASE):
                self.refuse("Coupure d'accès possible : " + " ; ".join(lk["cut"]) + f". Renvoie la requête avec acknowledge_cut_access=true et type_name=\"{PHRASE}\"", status.HTTP_409_CONFLICT)
        elif lk["live"] and not body.acknowledge_live:
            self.refuse("SDN : " + " ; ".join(lk["live"]) + ". Renvoie la requête avec acknowledge_live=true pour confirmer", status.HTTP_409_CONFLICT)
        return None

    async def opt(self, path, /, **kw):
        """Lecture facultative (droit ou fonction absente : liste vide, sans journal d'erreur)."""
        try:
            return await _px(self.db, self.factory, self.conn_id, "get", path, **kw)
        except HTTPException:
            return None

    async def zones(self):
        return shape_zones(await self.px("get", "/cluster/sdn/zones", pending=1))

    async def vnets(self):
        return shape_vnets(await self.px("get", "/cluster/sdn/vnets", pending=1))

    async def subnets(self, vnet):
        return shape_subnets(await self.px("get", f"/cluster/sdn/vnets/{vnet}/subnets", pending=1))


INERT = {"cut": [], "live": [], "inert": True}


def _cfg(row: dict | None, fields) -> dict:
    return {k: v for k, v in (row or {}).items() if k in fields and v not in (None, [], "")}


def _norm(v):
    return sorted(v) if isinstance(v, list) and v and isinstance(v[0], str) else v


def _same(want: dict, got: dict) -> bool:
    return all(_norm(got.get(k)) == _norm(v) for k, v in want.items() if k != "dhcp_range")


# ------------------------------------------------------------------ lecture
@router.get("/zones")
async def list_zones(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    return shape_zones(await _px(db, factory, conn_id, "get", "/cluster/sdn/zones", pending=1))


@router.get("/vnets")
async def list_vnets(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    return shape_vnets(await _px(db, factory, conn_id, "get", "/cluster/sdn/vnets", pending=1))


@router.get("/vnets/{vnet}/subnets")
async def list_subnets(conn_id: int, vnet: str = VNET_P, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    try:
        return shape_subnets(await _px(db, factory, conn_id, "get", f"/cluster/sdn/vnets/{vnet}/subnets", pending=1))
    except HTTPException as e:
        if "does not exist" in str(e.detail):             # Proxmox répond 500 « sdn vnet '…' does not exist » : c'est un 404 (constaté en réel)
            raise HTTPException(404, "VNet inconnu") from None
        raise


# ------------------------------------------------------------------ zones
async def _zone_op(op: str, ctx: Ctx, zone: str, body, clear: list[str], type_: str | None):
    zones = await ctx.zones()
    cur = next((z for z in zones if z["zone"] == zone and z["state"] != "deleted"), None)
    change = {k: getattr(body, k) for k in body.model_fields_set if k in ZONE_FIELDS and getattr(body, k) is not None}
    if op == "create":
        if cur is not None:
            ctx.refuse("Cette zone existe déjà", status.HTTP_409_CONFLICT)
    elif cur is None:
        ctx.refuse("Zone inconnue", status.HTTP_404_NOT_FOUND)
    else:
        type_ = cur["type"]
    new = None
    if op == "delete":
        used = sorted(v["vnet"] for v in await ctx.vnets() if v["zone"] == zone and v["state"] != "deleted")
        if used:
            ctx.refuse(f"Zone utilisée par {', '.join(used)} : supprime d'abord ces VNets", status.HTTP_409_CONFLICT)
    else:
        if op == "update":
            if set(clear) - set(ZONE_FIELDS) or set(clear) & set(change):
                ctx.refuse("Champ non retirable, ou à la fois modifié et retiré", 422)
            if not change and not clear:
                ctx.refuse("Aucune modification demandée", 422)
        new = {**_cfg(cur, ZONE_FIELDS), **change}
        for k in clear:
            new.pop(k, None)
        try:
            check_zone(type_, new)
        except ValueError as e:
            ctx.refuse(str(e), 422)
    params = {}
    if op == "create":
        params = {"zone": zone, "type": type_, **params_of(change)}
    elif op == "update":
        params = params_of(change)
        if clear:
            params["delete"] = ",".join(wire(k) for k in clear)
        if cur["digest"]:
            params["digest"] = cur["digest"]
    if (r := ctx.gate(body, INERT, {"params": {k: v for k, v in params.items() if k != "digest"}})) is not None:
        return r
    if op == "create":
        await ctx.px("post", "/cluster/sdn/zones", **params)
    elif op == "update":
        await ctx.px("put", f"/cluster/sdn/zones/{zone}", **params)
    else:
        await ctx.px("delete", f"/cluster/sdn/zones/{zone}")
    row = next((z for z in await ctx.zones() if z["zone"] == zone), None)
    ok = (row is None or row["state"] == "deleted") if op == "delete" else (row is not None and row["type"] == type_ and _same(new, _cfg(row, ZONE_FIELDS)))
    if not ok:
        ctx.refuse("Proxmox n'a pas enregistré la modification", status.HTTP_502_BAD_GATEWAY)
    ctx.log("started", f"{op} zone {type_ or ''} {zone} (en attente, non appliquée)")
    return {"staged": True, "applied": False}


@router.post("/zones")
async def create_zone(body: ZoneCreate, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _zone_op("create", Ctx(db, factory, user, conn_id, "sdn-zone-create", body.zone), body.zone, body, [], body.type)


@router.put("/zones/{zone}")
async def update_zone(body: ZoneUpdate, conn_id: int, zone: str = ZONE_P, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                      user: AdminUser = Depends(current_user)):
    return await _zone_op("update", Ctx(db, factory, user, conn_id, "sdn-zone-update", zone), zone, body, list(body.clear), None)


@router.delete("/zones/{zone}")
async def delete_zone(conn_id: int, zone: str = ZONE_P, confirm: bool = Query(default=False), dry_run: bool = Query(default=False), db: Session = Depends(get_db),
                      factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _zone_op("delete", Ctx(db, factory, user, conn_id, "sdn-zone-delete", zone), zone, Locks(confirm=confirm, dry_run=dry_run), [], None)


# ------------------------------------------------------------------ VNets
async def _vnet_op(op: str, ctx: Ctx, vnet: str, body, clear: list[str], zone: str | None):
    vnets = await ctx.vnets()
    cur = next((v for v in vnets if v["vnet"] == vnet and v["state"] != "deleted"), None)
    change = {k: getattr(body, k) for k in body.model_fields_set if k in VNET_FIELDS and getattr(body, k) is not None}
    if op == "create":
        if cur is not None:
            ctx.refuse("Ce VNet existe déjà", status.HTTP_409_CONFLICT)
        zrow = next((z for z in await ctx.zones() if z["zone"] == zone and z["state"] != "deleted"), None)
        if zrow is None:
            ctx.refuse("Zone inconnue", 422)
    elif cur is None:
        ctx.refuse("VNet inconnu", status.HTTP_404_NOT_FOUND)
    else:
        zone = cur["zone"]
        zrow = next((z for z in await ctx.zones() if z["zone"] == zone), None)
    new = None
    if op == "delete":
        used = [s["subnet"] for s in await ctx.subnets(vnet) if s["state"] != "deleted"]
        if used:
            ctx.refuse(f"Ce VNet a des sous-réseaux ({', '.join(used)}) : supprime-les d'abord", status.HTTP_409_CONFLICT)
    else:
        if op == "update":
            if set(clear) - set(VNET_FIELDS) or set(clear) & set(change):
                ctx.refuse("Champ non retirable, ou à la fois modifié et retiré", 422)
            if not change and not clear:
                ctx.refuse("Aucune modification demandée", 422)
        new = {**_cfg(cur, VNET_FIELDS), **change}
        for k in clear:
            new.pop(k, None)
        ztype = zrow["type"] if zrow else None
        if ztype in ("vlan", "qinq") and not new.get("tag") and op == "create":
            ctx.refuse("Un VNet d'une zone VLAN exige un « tag »", 422)
        if ztype in ("vlan", "qinq") and new.get("tag", 1) > 4094:
            ctx.refuse("Tag VLAN : 1 à 4094", 422)
        if ztype == "simple" and new.get("tag"):
            ctx.refuse("Une zone simple n'a pas de tag", 422)
    params = {}
    if op == "create":
        params = {"vnet": vnet, "zone": zone, **params_of(change)}
    elif op == "update":
        params = params_of(change)
        if clear:
            params["delete"] = ",".join(wire(k) for k in clear)
        if cur["digest"]:
            params["digest"] = cur["digest"]
    if (r := ctx.gate(body, INERT, {"params": {k: v for k, v in params.items() if k != "digest"}})) is not None:
        return r
    if op == "create":
        await ctx.px("post", "/cluster/sdn/vnets", **params)
    elif op == "update":
        await ctx.px("put", f"/cluster/sdn/vnets/{vnet}", **params)
    else:
        await ctx.px("delete", f"/cluster/sdn/vnets/{vnet}")
    row = next((v for v in await ctx.vnets() if v["vnet"] == vnet), None)
    ok = (row is None or row["state"] == "deleted") if op == "delete" else (row is not None and (op == "update" or row["zone"] == zone) and _same(new, _cfg(row, VNET_FIELDS)))
    if not ok:
        ctx.refuse("Proxmox n'a pas enregistré la modification", status.HTTP_502_BAD_GATEWAY)
    ctx.log("started", f"{op} vnet {vnet} (en attente, non appliquée)")
    return {"staged": True, "applied": False}


@router.post("/vnets")
async def create_vnet(body: VnetCreate, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _vnet_op("create", Ctx(db, factory, user, conn_id, "sdn-vnet-create", body.vnet), body.vnet, body, [], body.zone)


@router.put("/vnets/{vnet}")
async def update_vnet(body: VnetUpdate, conn_id: int, vnet: str = VNET_P, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                      user: AdminUser = Depends(current_user)):
    return await _vnet_op("update", Ctx(db, factory, user, conn_id, "sdn-vnet-update", vnet), vnet, body, list(body.clear), None)


@router.delete("/vnets/{vnet}")
async def delete_vnet(conn_id: int, vnet: str = VNET_P, confirm: bool = Query(default=False), dry_run: bool = Query(default=False), db: Session = Depends(get_db),
                      factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _vnet_op("delete", Ctx(db, factory, user, conn_id, "sdn-vnet-delete", vnet), vnet, Locks(confirm=confirm, dry_run=dry_run), [], None)


# ------------------------------------------------------------------ sous-réseaux
async def _subnet_op(op: str, ctx: Ctx, vnet: str, sid: str | None, cidr: str | None, body, clear: list[str]):
    vrow = next((v for v in await ctx.vnets() if v["vnet"] == vnet and v["state"] != "deleted"), None)
    if vrow is None:
        ctx.refuse("VNet inconnu", status.HTTP_404_NOT_FOUND)
    subs = await ctx.subnets(vnet)
    if op == "create":
        sid = subnet_id(vrow["zone"], cidr)
    cur = next((s for s in subs if s["subnet"] == sid and s["state"] != "deleted"), None)
    change = {k: getattr(body, k) for k in body.model_fields_set if k in SUBNET_FIELDS and getattr(body, k) is not None}
    if "dhcp_range" in change:
        change["dhcp_range"] = [{"start": r.start, "end": r.end} for r in body.dhcp_range]
    if op == "create":
        if cur is not None:
            ctx.refuse("Ce sous-réseau existe déjà", status.HTTP_409_CONFLICT)
        overlap = [s["subnet"] for s in subs if s["cidr"] and s["state"] != "deleted" and _overlap(s["cidr"], cidr)]
        if overlap:
            ctx.refuse(f"Chevauche {', '.join(overlap)}", status.HTTP_409_CONFLICT)
    elif cur is None:
        ctx.refuse("Sous-réseau inconnu", status.HTTP_404_NOT_FOUND)
    else:
        cidr = cur["cidr"]
    new = None
    if op != "delete":
        if op == "update":
            if set(clear) - set(SUBNET_FIELDS) or set(clear) & set(change):
                ctx.refuse("Champ non retirable, ou à la fois modifié et retiré", 422)
            if not change and not clear:
                ctx.refuse("Aucune modification demandée", 422)
        new = {**_cfg(cur, SUBNET_FIELDS), **change}
        for k in clear:
            new.pop(k, None)
        try:
            if not cidr:
                raise ValueError("Réseau du sous-réseau illisible")
            check_subnet(cidr, new)
        except ValueError as e:
            ctx.refuse(str(e), 422)
    params = {}
    if op == "create":
        # `vnet` aussi dans le corps : obligatoire chez Proxmox pour créer un sous-réseau (constaté en réel le 2026-11-13, sinon « Parameter verification failed »)
        params = {"subnet": sid, "type": "subnet", "vnet": vnet, **params_of(change)}
    elif op == "update":
        params = params_of(change)
        if clear:
            params["delete"] = ",".join(wire(k) for k in clear)
        if cur["digest"]:
            params["digest"] = cur["digest"]
    if (r := ctx.gate(body, INERT, {"params": {k: v for k, v in params.items() if k != "digest"}})) is not None:
        return r
    base = f"/cluster/sdn/vnets/{vnet}/subnets"
    if op == "create":
        await ctx.px("post", base, **params)
    elif op == "update":
        await ctx.px("put", f"{base}/{sid}", **params)
    else:
        await ctx.px("delete", f"{base}/{sid}")
    row = next((s for s in await ctx.subnets(vnet) if s["subnet"] == sid), None)
    ok = (row is None or row["state"] == "deleted") if op == "delete" else (row is not None and _same({k: v for k, v in new.items()}, _cfg(row, SUBNET_FIELDS)))
    if not ok:
        ctx.refuse("Proxmox n'a pas enregistré la modification", status.HTTP_502_BAD_GATEWAY)
    ctx.log("started", f"{op} sous-réseau {sid} (en attente, non appliqué)")
    return {"staged": True, "applied": False, "subnet": sid}


def _overlap(a: str, b: str) -> bool:
    import ipaddress
    try:
        return ipaddress.ip_network(a, strict=False).overlaps(ipaddress.ip_network(b, strict=False))
    except ValueError:
        return False


@router.post("/vnets/{vnet}/subnets")
async def create_subnet(body: SubnetCreate, conn_id: int, vnet: str = VNET_P, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                        user: AdminUser = Depends(current_user)):
    return await _subnet_op("create", Ctx(db, factory, user, conn_id, "sdn-subnet-create", f"{vnet}:{body.subnet}"), vnet, None, body.subnet, body, [])


@router.put("/vnets/{vnet}/subnets/{subnet}")
async def update_subnet(body: SubnetUpdate, conn_id: int, vnet: str = VNET_P, subnet: str = SUBNET_P, db: Session = Depends(get_db),
                        factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _subnet_op("update", Ctx(db, factory, user, conn_id, "sdn-subnet-update", f"{vnet}:{subnet}"), vnet, subnet, None, body, list(body.clear))


@router.delete("/vnets/{vnet}/subnets/{subnet}")
async def delete_subnet(conn_id: int, vnet: str = VNET_P, subnet: str = SUBNET_P, confirm: bool = Query(default=False), dry_run: bool = Query(default=False),
                        db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _subnet_op("delete", Ctx(db, factory, user, conn_id, "sdn-subnet-delete", f"{vnet}:{subnet}"), vnet, subnet, None, Locks(confirm=confirm, dry_run=dry_run), [])


# ------------------------------------------------------------------ appliquer / annuler
async def _pending(ctx: Ctx):
    """Zones, VNets et sous-réseaux en attente (`{zones, vnets, subnets}` : identifiants)."""
    zones, vnets = await ctx.zones(), await ctx.vnets()
    subs = [s["subnet"] for v in vnets if v["state"] != "deleted" for s in await ctx.subnets(v["vnet"]) if s["state"]]
    from ..sdnextra import shape_controllers, shape_fabric_nodes, shape_fabrics
    ctrls = shape_controllers(await ctx.opt("/cluster/sdn/controllers", pending=1))
    fabs = shape_fabrics(await ctx.opt("/cluster/sdn/fabrics/fabric", pending=1))
    fnodes = [f"{f['id']}/{n['node']}" for f in fabs if f["state"] != "deleted" for n in shape_fabric_nodes(await ctx.opt(f"/cluster/sdn/fabrics/node/{f['id']}", pending=1)) if n["state"]]
    return zones, vnets, {"zones": [z["zone"] for z in zones if z["state"]], "vnets": [v["vnet"] for v in vnets if v["state"]], "subnets": subs,
                          "controllers": [c["controller"] for c in ctrls if c["state"]], "fabrics": [f["id"] for f in fabs if f["state"]] + fnodes}


def _has_pending(pend: dict) -> bool:
    return any(pend.values())


@router.post("/apply")
async def apply(body: Locks, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Applique la configuration SDN en attente sur tous les nœuds."""
    ctx = Ctx(db, factory, user, conn_id, "sdn-apply", "cluster")
    zones, vnets, pend = await _pending(ctx)
    if not _has_pending(pend):
        ctx.refuse("Aucune modification SDN en attente", status.HTTP_409_CONFLICT)
    lk = apply_locks(zones, vnets, pend["controllers"] + pend["fabrics"])
    if (r := ctx.gate(body, lk, {"pending": pend})) is not None:
        return r
    upid = await ctx.px("put", "/cluster/sdn")
    ctx.log("started", "configuration SDN appliquée" + (" ; touche le réseau des nœuds ou supprime des objets" if lk["cut"] else ""))
    return {"applied": True, "task": upid if isinstance(upid, str) and len(upid) < 300 else None, "locks": lk}


@router.post("/rollback")
async def rollback(body: Locks, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Annule la configuration SDN en attente (inerte : rien n'avait été appliqué)."""
    ctx = Ctx(db, factory, user, conn_id, "sdn-rollback", "cluster")
    _, _, pend = await _pending(ctx)
    if not _has_pending(pend):
        ctx.refuse("Aucune modification SDN en attente", status.HTTP_409_CONFLICT)
    if (r := ctx.gate(body, INERT, {"pending": pend})) is not None:
        return r
    await ctx.px("post", "/cluster/sdn/rollback")
    if _has_pending((await _pending(ctx))[2]):
        ctx.refuse("Proxmox n'a pas annulé les modifications", status.HTTP_502_BAD_GATEWAY)
    ctx.log("started", "configuration SDN en attente annulée")
    return {"rolled_back": True}
