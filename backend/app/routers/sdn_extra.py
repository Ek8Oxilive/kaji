"""SDN, suite : contrôleurs, IPAM, DNS, fabrics et nœuds de fabric. Validation : `app/sdnextra.py`. Appliquer / annuler : `routers/sdn.py`."""
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import SecretStr
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..sdnextra import (CTRL_FIELDS, CTRL_ID, DNS_FIELDS, FABRIC_FIELDS, FABRIC_ID, IPAM_FIELDS, NODE, OBJ_ID, CtrlCreate, CtrlUpdate, DnsCreate, DnsUpdate, FabricCreate,
                        FabricNode, FabricUpdate, IpamCreate, IpamUpdate, check_controller, check_fabric, check_ipam, shape_controllers, shape_dns, shape_fabric_nodes,
                        shape_fabrics, shape_ipams)
from ..sdnspec import Locks, params_of, wire
from .auth import current_user
from .cluster import Factory, _px
from .sdn import INERT, Ctx

router = APIRouter(prefix="/api/connections/{conn_id}/sdn", tags=["sdn"], dependencies=[Depends(current_user)])

SECRETS = ("token", "key")
LIVE = {"cut": [], "live": ["une zone SDN utilise cet objet : la modification s'applique tout de suite à son adressage ou à son DNS"], "inert": False}


def _cfg(row, fields):
    return {k: v for k, v in (row or {}).items() if k in fields and v not in (None, [], "")}


def _norm(v):
    return sorted(v) if isinstance(v, list) and v and isinstance(v[0], str) else v


def _same(want: dict, got: dict) -> bool:
    return all(_norm(got.get(k)) == _norm(v) for k, v in want.items() if k not in SECRETS)


def _mask(params: dict) -> dict:
    return {k: ("***" if k in SECRETS else v) for k, v in params.items() if k != "digest"}


def _plain(change: dict) -> dict:
    return {k: (v.get_secret_value() if isinstance(v, SecretStr) else v) for k, v in change.items()}


class Spec:
    def __init__(self, name, idkey, path, shape, fields, pending, check, guard=None, live=None):
        self.name, self.idkey, self.path, self.shape, self.fields, self.pending, self.check, self.guard, self.live = name, idkey, path, shape, fields, pending, check, guard, live


async def _list(ctx: Ctx, sp: Spec):
    return sp.shape(await ctx.px("get", sp.path, **({"pending": 1} if sp.pending else {})))


async def _guard_ctrl(ctx, oid):
    return sorted(z["zone"] for z in await ctx.zones() if z.get("controller") == oid and z["state"] != "deleted")


async def _guard_ipam(ctx, oid):
    if oid == "pve":
        return ["(IPAM intégré : jamais supprimé)"]
    return sorted(z["zone"] for z in await ctx.zones() if z.get("ipam") == oid and z["state"] != "deleted")


async def _guard_dns(ctx, oid):
    return sorted(z["zone"] for z in await ctx.zones() if oid in (z.get("dns"), z.get("reversedns")) and z["state"] != "deleted")


async def _guard_fabric(ctx, oid):
    used = [c["controller"] for c in shape_controllers(await ctx.px("get", "/cluster/sdn/controllers", pending=1)) if c.get("fabric") == oid and c["state"] != "deleted"]
    nodes = shape_fabric_nodes(await ctx.px("get", f"/cluster/sdn/fabrics/node/{oid}", pending=1))
    return sorted(used + [f"nœud {n['node']}" for n in nodes if n["state"] != "deleted"])


async def _live_ipam(ctx, oid):
    return any(z.get("ipam") == oid for z in await ctx.zones())


async def _live_dns(ctx, oid):
    return any(oid in (z.get("dns"), z.get("reversedns")) for z in await ctx.zones())


SPECS = {
    "controllers": Spec("contrôleur", "controller", "/cluster/sdn/controllers", shape_controllers, CTRL_FIELDS, True, check_controller, _guard_ctrl),
    "ipams": Spec("IPAM", "ipam", "/cluster/sdn/ipams", shape_ipams, IPAM_FIELDS, False, check_ipam, _guard_ipam, _live_ipam),
    "dns": Spec("DNS", "dns", "/cluster/sdn/dns", shape_dns, DNS_FIELDS, False, lambda t, c: None, _guard_dns, _live_dns),
    "fabrics": Spec("fabric", "id", "/cluster/sdn/fabrics/fabric", shape_fabrics, FABRIC_FIELDS, True, lambda t, c: check_fabric(t, c), _guard_fabric),
}
TYPEKEY = {"controllers": "type", "ipams": "type", "dns": "type", "fabrics": "protocol"}


async def _op(kind: str, op: str, ctx: Ctx, oid: str, body, clear: list[str], type_: str | None):
    sp = SPECS[kind]
    rows = await _list(ctx, sp)
    cur = next((r for r in rows if r[sp.idkey] == oid), None)
    if sp.pending and cur is not None and cur["state"] == "deleted":
        cur = None
    secret_names = [k for k in SECRETS if k in body.model_fields_set and getattr(body, k) is not None]
    change = {k: getattr(body, k) for k in body.model_fields_set if (k in sp.fields or k in SECRETS) and getattr(body, k) is not None}
    if op == "create":
        if cur is not None:
            ctx.refuse(f"Ce {sp.name} existe déjà", status.HTTP_409_CONFLICT)
    elif cur is None:
        ctx.refuse(f"{sp.name.capitalize()} inconnu", status.HTTP_404_NOT_FOUND)
    else:
        type_ = cur[TYPEKEY[kind]]
        if type_ is None:
            ctx.refuse("Type non géré par Kaji", 422)
    new = None
    if op == "delete":
        used = await sp.guard(ctx, oid)
        if used:
            ctx.refuse(f"Utilisé par {', '.join(used)} : retire d'abord ces références", status.HTTP_409_CONFLICT)
    else:
        if op == "update":
            bad = set(clear) - set(sp.fields)
            if bad or set(clear) & set(change):
                ctx.refuse("Champ non retirable, ou à la fois modifié et retiré", 422)
            if not change and not clear:
                ctx.refuse("Aucune modification demandée", 422)
        new = {**_cfg(cur, sp.fields), **change}
        for k in clear:
            new.pop(k, None)
        try:
            sp.check(type_, new)
        except ValueError as e:
            ctx.refuse(str(e), 422)
    lk = INERT
    if op == "update" and sp.live is not None and await sp.live(ctx, oid):
        lk = LIVE
    wire_change = _plain(change)
    params = {}
    if op == "create":
        params = {sp.idkey: oid, TYPEKEY[kind]: type_, **params_of(wire_change)}
    elif op == "update":
        params = params_of(wire_change)
        if clear:
            params["delete"] = [k for k in clear] if kind == "fabrics" else ",".join(wire(k) for k in clear)
        if cur.get("digest"):
            params["digest"] = cur["digest"]
    if kind == "fabrics":                                    # les fabrics utilisent des noms à tiret bas (ip_prefix), pas des tirets
        params = {k.replace("-", "_"): v for k, v in params.items()}
    if (r := ctx.gate(body, lk, {"params": _mask(params), "secrets_set": sorted(secret_names)})) is not None:
        return r
    if op == "create":
        await ctx.px("post", sp.path, **params)
    elif op == "update":
        await ctx.px("put", f"{sp.path}/{oid}", **params)
    else:
        await ctx.px("delete", f"{sp.path}/{oid}")
    row = next((r for r in await _list(ctx, sp) if r[sp.idkey] == oid), None)
    gone = row is None or (sp.pending and row["state"] == "deleted")
    ok = gone if op == "delete" else (row is not None and (op == "update" or row[TYPEKEY[kind]] == type_) and _same(new, _cfg(row, sp.fields)))
    if not ok:
        ctx.refuse("Proxmox n'a pas enregistré la modification", status.HTTP_502_BAD_GATEWAY)
    ctx.log("started", f"{op} {sp.name} {oid}" + (f" ; secret défini : {', '.join(secret_names)}" if secret_names else "") + (" (en attente, non appliqué)" if sp.pending else ""))
    return {"staged" if sp.pending else "saved": True, "applied": False if sp.pending else True}


def _ctx(db, factory, user, conn_id, action, target):
    return Ctx(db, factory, user, conn_id, action, target)


# ---- lecture
@router.get("/controllers")
async def list_controllers(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    return shape_controllers(await _px(db, factory, conn_id, "get", "/cluster/sdn/controllers", pending=1))


@router.get("/ipams")
async def list_ipams(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    return shape_ipams(await _px(db, factory, conn_id, "get", "/cluster/sdn/ipams"))


@router.get("/dns")
async def list_dns(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    return shape_dns(await _px(db, factory, conn_id, "get", "/cluster/sdn/dns"))


@router.get("/fabrics")
async def list_fabrics(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    return shape_fabrics(await _px(db, factory, conn_id, "get", "/cluster/sdn/fabrics/fabric", pending=1))


@router.get("/fabrics/{fabric}/nodes")
async def list_fabric_nodes(conn_id: int, fabric: str = Path(pattern=FABRIC_ID.pattern), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    return shape_fabric_nodes(await _px(db, factory, conn_id, "get", f"/cluster/sdn/fabrics/node/{fabric}", pending=1))


# ---- écriture : contrôleurs
@router.post("/controllers")
async def create_controller(body: CtrlCreate, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _op("controllers", "create", _ctx(db, factory, user, conn_id, "sdn-controller-create", body.controller), body.controller, body, [], body.type)


@router.put("/controllers/{controller}")
async def update_controller(body: CtrlUpdate, conn_id: int, controller: str = Path(pattern=CTRL_ID.pattern), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                            user: AdminUser = Depends(current_user)):
    return await _op("controllers", "update", _ctx(db, factory, user, conn_id, "sdn-controller-update", controller), controller, body, list(body.clear), None)


@router.delete("/controllers/{controller}")
async def delete_controller(conn_id: int, controller: str = Path(pattern=CTRL_ID.pattern), confirm: bool = Query(default=False), dry_run: bool = Query(default=False), db: Session = Depends(get_db),
                            factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _op("controllers", "delete", _ctx(db, factory, user, conn_id, "sdn-controller-delete", controller), controller, Locks(confirm=confirm, dry_run=dry_run), [], None)


# ---- IPAM
@router.post("/ipams")
async def create_ipam(body: IpamCreate, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _op("ipams", "create", _ctx(db, factory, user, conn_id, "sdn-ipam-create", body.ipam), body.ipam, body, [], body.type)


@router.put("/ipams/{ipam}")
async def update_ipam(body: IpamUpdate, conn_id: int, ipam: str = Path(pattern=OBJ_ID.pattern), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _op("ipams", "update", _ctx(db, factory, user, conn_id, "sdn-ipam-update", ipam), ipam, body, list(body.clear), None)


@router.delete("/ipams/{ipam}")
async def delete_ipam(conn_id: int, ipam: str = Path(pattern=OBJ_ID.pattern), confirm: bool = Query(default=False), dry_run: bool = Query(default=False), db: Session = Depends(get_db),
                      factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _op("ipams", "delete", _ctx(db, factory, user, conn_id, "sdn-ipam-delete", ipam), ipam, Locks(confirm=confirm, dry_run=dry_run), [], None)


# ---- DNS
@router.post("/dns")
async def create_dns(body: DnsCreate, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _op("dns", "create", _ctx(db, factory, user, conn_id, "sdn-dns-create", body.dns), body.dns, body, [], body.type)


@router.put("/dns/{dns}")
async def update_dns(body: DnsUpdate, conn_id: int, dns: str = Path(pattern=OBJ_ID.pattern), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _op("dns", "update", _ctx(db, factory, user, conn_id, "sdn-dns-update", dns), dns, body, list(body.clear), None)


@router.delete("/dns/{dns}")
async def delete_dns(conn_id: int, dns: str = Path(pattern=OBJ_ID.pattern), confirm: bool = Query(default=False), dry_run: bool = Query(default=False), db: Session = Depends(get_db),
                     factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _op("dns", "delete", _ctx(db, factory, user, conn_id, "sdn-dns-delete", dns), dns, Locks(confirm=confirm, dry_run=dry_run), [], None)


# ---- fabrics
@router.post("/fabrics")
async def create_fabric(body: FabricCreate, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _op("fabrics", "create", _ctx(db, factory, user, conn_id, "sdn-fabric-create", body.id), body.id, body, [], body.protocol)


@router.put("/fabrics/{fabric}")
async def update_fabric(body: FabricUpdate, conn_id: int, fabric: str = Path(pattern=FABRIC_ID.pattern), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                        user: AdminUser = Depends(current_user)):
    return await _op("fabrics", "update", _ctx(db, factory, user, conn_id, "sdn-fabric-update", fabric), fabric, body, list(body.clear), None)


@router.delete("/fabrics/{fabric}")
async def delete_fabric(conn_id: int, fabric: str = Path(pattern=FABRIC_ID.pattern), confirm: bool = Query(default=False), dry_run: bool = Query(default=False), db: Session = Depends(get_db),
                        factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _op("fabrics", "delete", _ctx(db, factory, user, conn_id, "sdn-fabric-delete", fabric), fabric, Locks(confirm=confirm, dry_run=dry_run), [], None)


async def _node_op(op: str, ctx: Ctx, fabric: str, node: str, body):
    frow = next((f for f in shape_fabrics(await ctx.px("get", "/cluster/sdn/fabrics/fabric", pending=1)) if f["id"] == fabric and f["state"] != "deleted"), None)
    if frow is None:
        ctx.refuse("Fabric inconnu", status.HTTP_404_NOT_FOUND)
    nodes = shape_fabric_nodes(await ctx.px("get", f"/cluster/sdn/fabrics/node/{fabric}", pending=1))
    cur = next((n for n in nodes if n["node"] == node and n["state"] != "deleted"), None)
    if op == "create" and cur is not None:
        ctx.refuse("Ce nœud est déjà dans le fabric", status.HTTP_409_CONFLICT)
    if op != "create" and cur is None:
        ctx.refuse("Nœud inconnu dans ce fabric", status.HTTP_404_NOT_FOUND)
    new = None
    params: dict = {}
    if op != "delete":
        new = {"ip": cur["ip"] if cur else None, "ip6": cur["ip6"] if cur else None, "interfaces": list(cur["interfaces"]) if cur else []}
        if body.ip is not None:
            new["ip"] = body.ip
        if body.ip6 is not None:
            new["ip6"] = body.ip6
        if body.interfaces is not None:
            new["interfaces"] = [i.name for i in body.interfaces]
        if not (new["ip"] or new["ip6"]):
            ctx.refuse("Un nœud de fabric exige ip ou ip6", 422)
        params = {"protocol": frow["protocol"], **({"node_id": node} if op == "create" else {}), **{k: v for k, v in (("ip", new["ip"]), ("ip6", new["ip6"])) if v},
                  "interfaces": [f"name={n}" for n in new["interfaces"]]}
        if op == "update" and cur.get("digest"):
            params["digest"] = cur["digest"]
    if (r := ctx.gate(body, INERT, {"params": _mask(params)})) is not None:
        return r
    base = f"/cluster/sdn/fabrics/node/{fabric}"
    if op == "create":
        await ctx.px("post", base, **params)
    elif op == "update":
        await ctx.px("put", f"{base}/{node}", **params)
    else:
        await ctx.px("delete", f"{base}/{node}")
    row = next((n for n in shape_fabric_nodes(await ctx.px("get", base, pending=1)) if n["node"] == node), None)
    ok = (row is None or row["state"] == "deleted") if op == "delete" else (row is not None and (row["ip"], row["ip6"], sorted(row["interfaces"])) == (new["ip"], new["ip6"], sorted(new["interfaces"])))
    if not ok:
        ctx.refuse("Proxmox n'a pas enregistré la modification", status.HTTP_502_BAD_GATEWAY)
    ctx.log("started", f"{op} nœud {node} du fabric {fabric} (en attente, non appliqué)")
    return {"staged": True, "applied": False}


@router.post("/fabrics/{fabric}/nodes/{node}")
async def create_fabric_node(body: FabricNode, conn_id: int, fabric: str = Path(pattern=FABRIC_ID.pattern), node: str = Path(pattern=NODE.pattern), db: Session = Depends(get_db),
                             factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _node_op("create", _ctx(db, factory, user, conn_id, "sdn-fabric-node-create", f"{fabric}:{node}"), fabric, node, body)


@router.put("/fabrics/{fabric}/nodes/{node}")
async def update_fabric_node(body: FabricNode, conn_id: int, fabric: str = Path(pattern=FABRIC_ID.pattern), node: str = Path(pattern=NODE.pattern), db: Session = Depends(get_db),
                             factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _node_op("update", _ctx(db, factory, user, conn_id, "sdn-fabric-node-update", f"{fabric}:{node}"), fabric, node, body)


@router.delete("/fabrics/{fabric}/nodes/{node}")
async def delete_fabric_node(conn_id: int, fabric: str = Path(pattern=FABRIC_ID.pattern), node: str = Path(pattern=NODE.pattern), confirm: bool = Query(default=False), dry_run: bool = Query(default=False),
                             db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _node_op("delete", _ctx(db, factory, user, conn_id, "sdn-fabric-node-delete", f"{fabric}:{node}"), fabric, node, Locks(confirm=confirm, dry_run=dry_run))
