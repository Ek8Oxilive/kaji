"""Haute disponibilité en ÉCRITURE : ressources (`vm:ID` / `ct:ID`), règles (`node-affinity` / `resource-affinity`), migrer, relocaliser.

Verrous, `dry_run` et validation : `app/hawrite.py`. Droit requis chez Proxmox : `Sys.Console` sur `/`. Chaque écriture relit l'état avant (digest, existence, verrous)
et après (le changement est-il bien là ?), et est auditée, refus compris.
"""
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..deps import get_client_factory
from ..haspec import shape_ha_resources, shape_ha_rules
from ..hawrite import (INACTIVE_STATES, PHRASE, RULE, SID, Locks, MoveBody, ResourceCreate, ResourceUpdate, RuleCreate, RuleUpdate, build_resource, build_rule,
                       gtype_of, locks, protected_hits, vmid_of)
from ..models import AdminUser
from .auth import current_user
from .cluster import Factory, _px, shape_guests, shape_status

router = APIRouter(prefix="/api/connections/{conn_id}/ha", tags=["ha-write"], dependencies=[Depends(current_user)])


class Ctx:
    """Contexte d'une écriture : appels Proxmox, audit, refus (toujours journalisés)."""

    def __init__(self, db: Session, factory: Factory, conn_id: int, user: AdminUser, action: str, target: str):
        self.db, self.factory, self.conn_id, self.user, self.action, self.target = db, factory, conn_id, user, action, target

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

    async def state(self) -> dict:
        return {"resources": shape_ha_resources(await self.px("get", "/cluster/ha/resources")), "rules": shape_ha_rules(await self.px("get", "/cluster/ha/rules")),
                "cluster": shape_status(await self.px("get", "/cluster/status")), "guests": shape_guests(await self.px("get", "/cluster/resources", type="vm"))}

    def gate(self, body: Locks, lk: dict, preview: dict):
        """Applique les verrous. Renvoie la réponse de `dry_run`, ou None si l'écriture peut partir."""
        if body.dry_run:
            return {"dry_run": True, **preview, "locks": lk, "phrase": PHRASE if lk["cut"] else None}
        if lk["cut"]:
            if not (body.acknowledge_cut_access and body.type_name == PHRASE):
                self.refuse("Coupure possible : " + " ; ".join(lk["cut"]) + f". Renvoie la requête avec acknowledge_cut_access=true et type_name=\"{PHRASE}\"", status.HTTP_409_CONFLICT)
        elif lk["live"] and not body.acknowledge_live:
            self.refuse("Effet immédiat : " + " ; ".join(lk["live"]) + ". Renvoie la requête avec acknowledge_live=true pour confirmer", status.HTTP_409_CONFLICT)
        return None

    def need_confirm(self, body: Locks):
        if not body.dry_run and not body.confirm:
            self.refuse("Écriture HA : renvoie la requête avec confirm=true (ou dry_run=true pour voir les verrous)", 400)

    def forbid_protected(self, sids: list[str]):
        hit = protected_hits(sids, get_settings().protected_vmids)
        if hit:
            self.refuse(f"Machine protégée (KAJI_PROTECTED_VMIDS) : {', '.join(hit)} ne peut pas être gérée par la HA depuis Kaji, même confirmé", status.HTTP_403_FORBIDDEN)


def _by_key(rows: list[dict], key: str, value: str) -> dict | None:
    return next((r for r in rows if r[key] == value), None)


def _comigrated(rules: list[dict], sid: str) -> set[str]:
    """Ressources qu'une règle d'affinité positive actives entraîne avec `sid` (fermeture transitive)."""
    group = {sid}
    changed = True
    while changed:
        changed = False
        for r in rules:
            if r["type"] == "resource-affinity" and r["affinity"] == "positive" and not r["disable"] and group & set(r["resources"]) and not set(r["resources"]) <= group:
                group |= set(r["resources"])
                changed = True
    return group - {sid}


def _ignored_by_strict_rules(rules: list[dict], sids: set[str], target: str) -> list[dict]:
    """Règles de nœud strictes et actives qui visent une de `sids` mais n'autorisent pas `target` : la HA ignore alors la demande (rien ne bouge)."""
    out = []
    for r in rules:
        if r["type"] != "node-affinity" or not r["strict"] or r["disable"]:
            continue
        hit = sorted(sids & set(r["resources"]))
        allowed = [n["node"] for n in r["nodes"]]
        if hit and target not in allowed:
            out.append({"rule": r["rule"], "resources": hit, "nodes": allowed})
    return out


def _resource_ok(after: dict | None, params: dict, delete: list[str]) -> bool:
    if after is None:
        return False
    for k, v in params.items():
        got = after.get(k)
        if isinstance(got, bool):
            got = int(got)
        if got != v:
            return False
    return all(after.get(k) is None for k in delete)


def _rule_ok(after: dict | None, params: dict, delete: list[str]) -> bool:
    if after is None:
        return False
    for k, v in params.items():
        if k == "type":
            if after["type"] != v:
                return False
        elif k == "resources":
            if set(after["resources"]) != set(v.split(",")):
                return False
        elif k == "nodes":
            if {n["node"] for n in after["nodes"]} != {x.partition(":")[0] for x in v.split(",")}:
                return False
        elif k in ("strict", "disable"):
            if bool(after.get(k)) != bool(v):
                return False
        elif after.get(k) != v:
            return False
    return all(not after.get(k) for k in delete)


def _txt(params: dict, delete: list[str]) -> str:
    return ", ".join(f"{k}={'défini' if k == 'comment' else v}" for k, v in sorted(params.items())) + (f" ; retiré : {','.join(delete)}" if delete else "")


# ------------------------------------------------------------------ ressources
@router.post("/resources")
async def create_resource(body: ResourceCreate, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    c = Ctx(db, factory, conn_id, user, "ha-resource-create", body.sid)
    c.need_confirm(body)
    c.forbid_protected([body.sid])
    st = await c.state()
    guest = next((g for g in st["guests"] if g["vmid"] == vmid_of(body.sid) and g["type"] == gtype_of(body.sid)), None)
    if guest is None:
        c.refuse("Machine introuvable (type ou identifiant inconnu du cluster)", status.HTTP_404_NOT_FOUND)
    if guest["template"]:
        c.refuse("Un modèle ne peut pas être géré par la HA", status.HTTP_422_UNPROCESSABLE_ENTITY)
    if _by_key(st["resources"], "sid", body.sid):
        c.refuse("Cette machine est déjà une ressource HA", status.HTTP_409_CONFLICT)
    params, _ = build_resource(body, [])
    lk = locks("create", len(st["cluster"]["nodes"]), existing=False, activates=params.get("state", "started") not in INACTIVE_STATES)
    out = c.gate(body, lk, {"params": {"sid": body.sid, **params}})
    if out:
        return out
    await c.px("post", "/cluster/ha/resources", sid=body.sid, **params)
    after = _by_key(shape_ha_resources(await c.px("get", "/cluster/ha/resources")), "sid", body.sid)
    if not _resource_ok(after, params, []):
        c.refuse("Proxmox n'a pas appliqué la création", status.HTTP_502_BAD_GATEWAY)
    c.log("started", _txt(params, []))
    return {"created": body.sid, "locks": lk}


@router.put("/resources/{sid}")
async def update_resource(body: ResourceUpdate, conn_id: int, sid: str = Path(pattern=SID.pattern), db: Session = Depends(get_db),
                          factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    c = Ctx(db, factory, conn_id, user, "ha-resource-update", sid)
    c.need_confirm(body)
    c.forbid_protected([sid])
    st = await c.state()
    cur = _by_key(st["resources"], "sid", sid)
    if cur is None:
        c.refuse("Ressource HA introuvable", status.HTTP_404_NOT_FOUND)
    try:
        params, delete = build_resource(body, list(body.clear))
    except ValueError as e:
        c.refuse(str(e), status.HTTP_422_UNPROCESSABLE_ENTITY)
    if not params and not delete:
        c.refuse("Aucune modification demandée", status.HTTP_422_UNPROCESSABLE_ENTITY)
    lk = locks("update", len(st["cluster"]["nodes"]), existing=True, activates=params.get("state", cur["state"]) not in INACTIVE_STATES)
    out = c.gate(body, lk, {"params": params, "remove": delete})
    if out:
        return out
    send = dict(params)
    if delete:
        send["delete"] = ",".join(delete)
    if isinstance(cur.get("digest"), str):
        send["digest"] = cur["digest"]                                       # refus si la configuration a changé entre-temps
    await c.px("put", f"/cluster/ha/resources/{sid}", **send)
    if not _resource_ok(_by_key(shape_ha_resources(await c.px("get", "/cluster/ha/resources")), "sid", sid), params, delete):
        c.refuse("Proxmox n'a pas appliqué la modification", status.HTTP_502_BAD_GATEWAY)
    c.log("started", _txt(params, delete))
    return {"changed": sorted(params), "removed": delete, "locks": lk}


@router.delete("/resources/{sid}")
async def delete_resource(conn_id: int, sid: str = Path(pattern=SID.pattern), confirm: bool = Query(default=False), acknowledge_live: bool = Query(default=False),
                          acknowledge_cut_access: bool = Query(default=False), type_name: str | None = Query(default=None, max_length=40), dry_run: bool = Query(default=False),
                          db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Retire la machine de la HA (la machine elle-même n'est pas touchée). Refusé tant qu'une règle la cite : les règles ne sont jamais modifiées en douce."""
    body = Locks(confirm=confirm, acknowledge_live=acknowledge_live, acknowledge_cut_access=acknowledge_cut_access, type_name=type_name, dry_run=dry_run)
    c = Ctx(db, factory, conn_id, user, "ha-resource-delete", sid)
    c.need_confirm(body)                                                     # retirer une machine protégée de la HA reste permis : c'est le sens sûr
    st = await c.state()
    if _by_key(st["resources"], "sid", sid) is None:
        c.refuse("Ressource HA introuvable", status.HTTP_404_NOT_FOUND)
    used = [r["rule"] for r in st["rules"] if sid in r["resources"]]
    if used:
        c.refuse(f"Cette ressource est citée par des règles ({', '.join(used)}) : retire-la d'abord de ces règles", status.HTTP_409_CONFLICT)
    lk = locks("delete", len(st["cluster"]["nodes"]), existing=True, activates=False)
    out = c.gate(body, lk, {"remove": [sid]})
    if out:
        return out
    await c.px("delete", f"/cluster/ha/resources/{sid}", purge=0)
    if _by_key(shape_ha_resources(await c.px("get", "/cluster/ha/resources")), "sid", sid) is not None:
        c.refuse("Proxmox n'a pas retiré la ressource", status.HTTP_502_BAD_GATEWAY)
    c.log("started", "retirée de la HA")
    return {"deleted": sid, "locks": lk}


async def _move(kind: str, body: MoveBody, conn_id: int, sid: str, db, factory, user):
    c = Ctx(db, factory, conn_id, user, f"ha-{kind}", f"{sid}->{body.node}")
    c.need_confirm(body)
    c.forbid_protected([sid])
    st = await c.state()
    if _by_key(st["resources"], "sid", sid) is None:
        c.refuse("Ressource HA introuvable", status.HTTP_404_NOT_FOUND)
    c.forbid_protected(sorted(_comigrated(st["rules"], sid)))                # une affinité positive entraînerait la machine de Kaji
    target = next((n for n in st["cluster"]["nodes"] if n["name"] == body.node), None)
    if target is None or not target["online"]:
        c.refuse("Nœud cible inconnu ou hors ligne", status.HTTP_422_UNPROCESSABLE_ENTITY)
    guest = next((g for g in st["guests"] if g["vmid"] == vmid_of(sid) and g["type"] == gtype_of(sid)), None)
    if guest is None:
        c.refuse("Machine introuvable", status.HTTP_404_NOT_FOUND)
    if guest["node"] == body.node:
        c.refuse("La machine est déjà sur ce nœud", status.HTTP_409_CONFLICT)
    lk = locks(kind, len(st["cluster"]["nodes"]), existing=True, activates=True)
    together = sorted(_comigrated(st["rules"], sid))
    ignored = _ignored_by_strict_rules(st["rules"], {sid, *together}, body.node)
    out = c.gate(body, lk, {"params": {"node": body.node}, "from": guest["node"], "comigrated": together, "ignored": ignored})
    if out:
        return out
    raw = await c.px("post", f"/cluster/ha/resources/{sid}/{kind}", node=body.node)
    info = raw if isinstance(raw, dict) else {}
    blocking_raw = info.get("blocking-resources") if isinstance(info.get("blocking-resources"), list) else []
    blocking = [{"sid": b["sid"], "cause": b.get("cause") if b.get("cause") in ("node-affinity", "resource-affinity") else None}
                for b in blocking_raw if isinstance(b, dict) and isinstance(b.get("sid"), str) and SID.fullmatch(b["sid"])][:64]
    co_raw = info.get("comigrated-resources") if isinstance(info.get("comigrated-resources"), list) else []
    comigrated = [x for x in co_raw if isinstance(x, str) and SID.fullmatch(x)][:64]
    c.log("started", f"{kind} demandé vers {body.node} (asynchrone, décidé par la HA)" + (f" ; règles strictes qui vont l'ignorer : {','.join(i['rule'] for i in ignored)}" if ignored else ""))
    return {"requested": body.node, "from": guest["node"], "blocking": blocking, "comigrated": comigrated, "ignored": ignored, "locks": lk}


@router.post("/resources/{sid}/migrate")
async def migrate_resource(body: MoveBody, conn_id: int, sid: str = Path(pattern=SID.pattern), db: Session = Depends(get_db),
                           factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Demande à la HA de migrer la machine vers un autre nœud (à chaud pour une VM, redémarrage pour un conteneur). Asynchrone : suivre l'état HA."""
    return await _move("migrate", body, conn_id, sid, db, factory, user)


@router.post("/resources/{sid}/relocate")
async def relocate_resource(body: MoveBody, conn_id: int, sid: str = Path(pattern=SID.pattern), db: Session = Depends(get_db),
                            factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Demande à la HA de relocaliser la machine (arrêt, déplacement, redémarrage). Asynchrone."""
    return await _move("relocate", body, conn_id, sid, db, factory, user)


# ------------------------------------------------------------------ règles
def _check_rule_refs(c: Ctx, st: dict, resources: list[str] | None, nodes: list | None):
    if resources is not None:
        missing = [s for s in resources if _by_key(st["resources"], "sid", s) is None]
        if missing:
            c.refuse(f"Ressource(s) HA inconnue(s) : {', '.join(missing)} (ajoute-les d'abord à la HA)", status.HTTP_422_UNPROCESSABLE_ENTITY)
    if nodes is not None:
        known = {n["name"] for n in st["cluster"]["nodes"]}
        unknown = [n.node for n in nodes if n.node not in known]
        if unknown:
            c.refuse(f"Nœud(s) inconnu(s) du cluster : {', '.join(unknown)}", status.HTTP_422_UNPROCESSABLE_ENTITY)


@router.post("/rules")
async def create_rule(body: RuleCreate, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    c = Ctx(db, factory, conn_id, user, "ha-rule-create", body.rule)
    c.need_confirm(body)
    c.forbid_protected(body.resources or [])
    st = await c.state()
    if _by_key(st["rules"], "rule", body.rule):
        c.refuse("Une règle porte déjà ce nom", status.HTTP_409_CONFLICT)
    _check_rule_refs(c, st, body.resources, body.nodes)
    try:
        params, _ = build_rule(body, [])
    except ValueError as e:
        c.refuse(str(e), status.HTTP_422_UNPROCESSABLE_ENTITY)
    lk = locks("create", len(st["cluster"]["nodes"]), existing=False, activates=not params.get("disable"))
    out = c.gate(body, lk, {"params": {"rule": body.rule, **params}})
    if out:
        return out
    await c.px("post", "/cluster/ha/rules", rule=body.rule, **params)
    if not _rule_ok(_by_key(shape_ha_rules(await c.px("get", "/cluster/ha/rules")), "rule", body.rule), params, []):
        c.refuse("Proxmox n'a pas appliqué la création", status.HTTP_502_BAD_GATEWAY)
    c.log("started", _txt(params, []))
    return {"created": body.rule, "locks": lk}


@router.put("/rules/{rule}")
async def update_rule(body: RuleUpdate, conn_id: int, rule: str = Path(pattern=RULE.pattern), db: Session = Depends(get_db),
                      factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    c = Ctx(db, factory, conn_id, user, "ha-rule-update", rule)
    c.need_confirm(body)
    st = await c.state()
    cur = _by_key(st["rules"], "rule", rule)
    if cur is None:
        c.refuse("Règle introuvable", status.HTTP_404_NOT_FOUND)
    if cur["type"] != body.type:
        c.refuse("Le type d'une règle ne peut pas changer : supprime-la puis recrée-la", status.HTTP_422_UNPROCESSABLE_ENTITY)
    _check_rule_refs(c, st, body.resources, body.nodes)
    try:
        params, delete = build_rule(body, list(body.clear))
    except ValueError as e:
        c.refuse(str(e), status.HTTP_422_UNPROCESSABLE_ENTITY)
    if set(params) <= {"type"} and not delete:
        c.refuse("Aucune modification demandée", status.HTTP_422_UNPROCESSABLE_ENTITY)
    disabled_after = bool(params["disable"]) if "disable" in params else False if "disable" in delete else bool(cur["disable"])
    effective = body.resources if body.resources is not None else cur["resources"]
    if body.resources is not None or not disabled_after:
        c.forbid_protected(effective)
    lk = locks("update", len(st["cluster"]["nodes"]), existing=True, activates=not disabled_after)
    out = c.gate(body, lk, {"params": params, "remove": delete})
    if out:
        return out
    send = dict(params)
    if delete:
        send["delete"] = ",".join(delete)
    if isinstance(cur.get("digest"), str):
        send["digest"] = cur["digest"]
    await c.px("put", f"/cluster/ha/rules/{rule}", **send)
    if not _rule_ok(_by_key(shape_ha_rules(await c.px("get", "/cluster/ha/rules")), "rule", rule), params, delete):
        c.refuse("Proxmox n'a pas appliqué la modification", status.HTTP_502_BAD_GATEWAY)
    c.log("started", _txt(params, delete))
    return {"changed": sorted(k for k in params if k != "type"), "removed": delete, "locks": lk}


@router.delete("/rules/{rule}")
async def delete_rule(conn_id: int, rule: str = Path(pattern=RULE.pattern), confirm: bool = Query(default=False), acknowledge_live: bool = Query(default=False),
                      acknowledge_cut_access: bool = Query(default=False), type_name: str | None = Query(default=None, max_length=40), dry_run: bool = Query(default=False),
                      db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    body = Locks(confirm=confirm, acknowledge_live=acknowledge_live, acknowledge_cut_access=acknowledge_cut_access, type_name=type_name, dry_run=dry_run)
    c = Ctx(db, factory, conn_id, user, "ha-rule-delete", rule)
    c.need_confirm(body)
    st = await c.state()
    if _by_key(st["rules"], "rule", rule) is None:
        c.refuse("Règle introuvable", status.HTTP_404_NOT_FOUND)
    lk = locks("delete", len(st["cluster"]["nodes"]), existing=True, activates=False)
    out = c.gate(body, lk, {"remove": [rule]})
    if out:
        return out
    await c.px("delete", f"/cluster/ha/rules/{rule}")
    if _by_key(shape_ha_rules(await c.px("get", "/cluster/ha/rules")), "rule", rule) is not None:
        c.refuse("Proxmox n'a pas supprimé la règle", status.HTTP_502_BAD_GATEWAY)
    c.log("started", "règle supprimée")
    return {"deleted": rule, "locks": lk}
