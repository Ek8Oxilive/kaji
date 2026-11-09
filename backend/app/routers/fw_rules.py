"""Règles du pare-feu (datacenter, nœud, machine, groupe de sécurité) : créer, modifier, supprimer, déplacer. Verrous et validation : `app/fwrules.py`."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..deps import get_client_factory
from ..fwrules import (CLEARABLE, FIELDS, PHRASE, RuleCreate, RuleLocks, RuleMove, RuleUpdate, check_action, effective, locks, params_of)
from ..fwoptions import RESTRICTIVE
from ..models import AdminUser
from ..networkspec import shape_named, shape_options, shape_rules
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}/firewall", tags=["firewall-write"], dependencies=[Depends(current_user)])
POS = Path(ge=0, le=10000)
LOCKMETA = {"confirm", "acknowledge_live", "acknowledge_cut_access", "type_name", "dry_run", "clear", "pos", "moveto"}


class Scope:
    def __init__(self, level: str, label: str, base: str, protected: bool = False):
        self.level, self.label, self.base, self.protected = level, label, base, protected


async def _run(op: str, sc: Scope, pos: int | None, body, conn_id: int, db: Session, factory: Factory, user: AdminUser):
    def log(st, detail=None):
        audit.record(db, username=user.username, connection_id=conn_id, action=f"fw-rule-{op}", target=f"{sc.label}#{pos if pos is not None else 'new'}", status=st, detail=detail)

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
    change = {k: getattr(body, k) for k in body.model_fields_set if k in FIELDS and getattr(body, k) is not None}
    clear = list(getattr(body, "clear", []))
    if op == "update":
        bad = [k for k in clear if k not in CLEARABLE]
        if bad or set(clear) & set(change):
            refuse("Champ non retirable, ou à la fois modifié et retiré", 422)
        if not change and not clear:
            refuse("Aucune modification demandée", 422)
    rules = shape_rules(await px("get", f"{sc.base}/rules"))
    cur = next((r for r in rules if r["pos"] == pos), None) if pos is not None else None
    if op != "create" and cur is None:
        refuse("Règle introuvable", status.HTTP_404_NOT_FOUND)
    if op == "move" and body.moveto >= len(rules):
        refuse("Position hors limites", 422)
    if op == "create" and body.pos is not None and body.pos > len(rules):
        refuse("Position hors limites", 422)
    cur_clean = {k: v for k, v in (cur or {}).items() if k in FIELDS and v is not None}
    new = None
    if op == "create":
        new = effective(None, {"enable": False, **change}, [])
    elif op == "update":
        new = effective(cur_clean, change, clear)
    elif op == "move":
        new = cur_clean
    if new is not None:
        if sc.level == "group" and new.get("type") not in ("in", "out"):
            refuse("Une règle de groupe est « in » ou « out »", 422)
        if sc.level == "guest" and new.get("type") == "forward":
            refuse("Pas de règle « forward » sur une machine", 422)
    if op in ("create", "update") and ("type" in change or "action" in change):
        groups = {g["name"] for g in shape_named(await px("get", "/cluster/firewall/groups"), "group")}
        try:
            check_action(new.get("type"), new.get("action"), groups)
        except ValueError as e:
            refuse(str(e), 422)
    if op in ("create", "update") and new.get("type") == "group" and "action" not in new:
        refuse("Un groupe de sécurité est requis", 422)
    if change.get("macro"):
        macros = {m.get("macro") for m in (await px("get", "/cluster/firewall/macros") or []) if isinstance(m, dict)}
        if change["macro"] not in macros:
            refuse("Macro inconnue", 422)
    cluster_on = bool(shape_options("cluster", await px("get", "/cluster/firewall/options")).get("enable"))
    if sc.level in ("cluster", "group"):
        lvl_opts = shape_options("cluster", await px("get", "/cluster/firewall/options"))
    else:
        lvl_opts = shape_options(sc.level, await px("get", f"{sc.base}/options"))
    active = cluster_on and (sc.level == "group" or bool(lvl_opts.get("enable")))
    restrictive_in = sc.level != "guest" and (lvl_opts.get("policy_in") or "DROP") in RESTRICTIVE
    if op == "create":
        lk = locks(sc.level, active, restrictive_in, None, new, sc.protected)
    elif op == "update":
        lk = locks(sc.level, active, restrictive_in, cur_clean, new, sc.protected)
    elif op == "delete":
        lk = locks(sc.level, active, restrictive_in, cur_clean, None, sc.protected)
    else:
        a = locks(sc.level, active, restrictive_in, None, cur_clean, sc.protected)
        b = locks(sc.level, active, restrictive_in, cur_clean, None, sc.protected)
        lk = {"cut": list(dict.fromkeys(a["cut"] + b["cut"])), "live": list(dict.fromkeys(a["live"] + b["live"]))}
        lk["inert"] = not (lk["cut"] or lk["live"])
    params = params_of({k: v for k, v in change.items()}) if op in ("create", "update") else {}
    if op == "create" and body.pos is not None:
        params["pos"] = body.pos
    if op == "create":
        params["enable"] = params.get("enable", 0)
    if op == "move":
        params["moveto"] = body.moveto
    if op == "update" and clear:
        params["delete"] = ",".join(("icmp-type" if k == "icmp_type" else k) for k in clear)
    if body.dry_run:
        return {"dry_run": True, "params": params, "locks": lk, "phrase": PHRASE if lk["cut"] else None}
    if lk["cut"]:
        if not (body.acknowledge_cut_access and body.type_name == PHRASE):
            refuse("Coupure d'accès possible : " + " ; ".join(lk["cut"]) + f". Renvoie la requête avec acknowledge_cut_access=true et type_name=\"{PHRASE}\"", status.HTTP_409_CONFLICT)
    elif lk["live"] and not body.acknowledge_live:
        refuse("Pare-feu actif : " + " ; ".join(lk["live"]) + ". Renvoie la requête avec acknowledge_live=true pour confirmer", status.HTTP_409_CONFLICT)
    send = dict(params)
    if op != "create":
        one = await px("get", f"{sc.base}/rules/{pos}")
        if isinstance(one, dict) and isinstance(one.get("digest"), str):
            send["digest"] = one["digest"]                                # refus si les règles ont changé entre-temps
    if op == "create":
        await px("post", f"{sc.base}/rules", **send)
    elif op == "delete":
        await px("delete", f"{sc.base}/rules/{pos}", **({"digest": send["digest"]} if "digest" in send else {}))
    else:
        await px("put", f"{sc.base}/rules/{pos}", **send)
    after = shape_rules(await px("get", f"{sc.base}/rules"))
    ok = {"create": len(after) == len(rules) + 1, "delete": len(after) == len(rules) - 1, "update": len(after) == len(rules), "move": len(after) == len(rules)}[op]
    if ok and op == "update":
        row = after[pos] if pos < len(after) else {}
        ok = all(row.get(k) == (bool(v) if k == "enable" else v) for k, v in change.items())
    if ok and op == "move":
        ok = after[body.moveto].get("action") == cur_clean.get("action") and after[body.moveto].get("dport") == cur_clean.get("dport")
    if not ok:
        refuse("Proxmox n'a pas appliqué la modification", status.HTTP_502_BAD_GATEWAY)
    log("started", ", ".join(f"{k}={v}" for k, v in sorted(params.items())) + ("" if not lk["inert"] else " ; niveau inactif : appliqué à l'activation"))
    return {"changed": True, "locks": lk}


def _cluster() -> Scope:
    return Scope("cluster", "datacenter", "/cluster/firewall")


def _node(node: str = Path(pattern=NODE)) -> Scope:
    return Scope("node", f"node:{node}", f"/nodes/{node}/firewall")


def _guest(node: str = Path(pattern=NODE), gtype: Literal["qemu", "lxc"] = Path(), vmid: int = Path(ge=100, le=999999999)) -> Scope:
    return Scope("guest", f"{gtype}/{vmid}@{node}", f"/nodes/{node}/{gtype}/{vmid}/firewall", vmid in get_settings().protected_vmids)


def _group(group: str = Path(pattern=r"^[A-Za-z][A-Za-z0-9\-_]{1,17}$")) -> Scope:
    return Scope("group", f"group:{group}", f"/cluster/firewall/groups/{group}")


def _register(prefix: str, dep):
    async def create(body: RuleCreate, conn_id: int, sc: Scope = Depends(dep), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                     user: AdminUser = Depends(current_user)):
        return await _run("create", sc, None, body, conn_id, db, factory, user)

    async def update(body: RuleUpdate, conn_id: int, pos: int = POS, sc: Scope = Depends(dep), db: Session = Depends(get_db),
                     factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
        return await _run("update", sc, pos, body, conn_id, db, factory, user)

    async def move(body: RuleMove, conn_id: int, pos: int = POS, sc: Scope = Depends(dep), db: Session = Depends(get_db),
                   factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
        return await _run("move", sc, pos, body, conn_id, db, factory, user)

    async def delete(conn_id: int, pos: int = POS, confirm: bool = Query(default=False), acknowledge_live: bool = Query(default=False),
                     acknowledge_cut_access: bool = Query(default=False), type_name: str | None = Query(default=None, max_length=40), dry_run: bool = Query(default=False),
                     sc: Scope = Depends(dep), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
        body = RuleLocks(confirm=confirm, acknowledge_live=acknowledge_live, acknowledge_cut_access=acknowledge_cut_access, type_name=type_name, dry_run=dry_run)
        return await _run("delete", sc, pos, body, conn_id, db, factory, user)

    router.add_api_route(f"{prefix}/rules", create, methods=["POST"])
    router.add_api_route(f"{prefix}/rules/{{pos}}", update, methods=["PUT"])
    router.add_api_route(f"{prefix}/rules/{{pos}}/move", move, methods=["PUT"])
    router.add_api_route(f"{prefix}/rules/{{pos}}", delete, methods=["DELETE"])


_register("/cluster", _cluster)
_register("/nodes/{node}", _node)
_register("/guests/{node}/{gtype}/{vmid}", _guest)
_register("/groups/{group}", _group)
