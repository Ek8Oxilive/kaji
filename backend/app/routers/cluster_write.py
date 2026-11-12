"""Cluster Proxmox en ÉCRITURE : créer un cluster, joindre un nœud, retirer un nœud (M10-2, option B de `docs/m10-cluster.md`).

Verrous, `dry_run` et validation : `app/clusterwrite.py`. Créer et joindre s'adressent au nœud ISOLÉ que la connexion désigne ; retirer s'adresse à un autre membre.
Chaque écriture relit l'état avant, est auditée (refus compris) et ne met jamais le mot de passe dans l'audit, la réponse ou une erreur.
"""
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from .. import audit
from ..clusterspec import shape_corosync_nodes
from ..clusterspec import shape_status as shape_cluster
from ..clusterwrite import NODE, PHRASE, CreateBody, JoinBody, Locks, build_create, build_join, remove_locks
from ..config import get_settings
from ..db import get_db
from ..deps import get_client_factory
from ..haspec import shape_ha_resources
from ..models import AdminUser
from .auth import current_user
from .cluster import Factory, _px, shape_guests

router = APIRouter(prefix="/api/connections/{conn_id}/cluster", tags=["cluster-write"], dependencies=[Depends(current_user)])


class Ctx:
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

    def need_confirm(self, body: Locks):
        if not body.dry_run and not body.confirm:
            self.refuse("Écriture du cluster : renvoie la requête avec confirm=true (ou dry_run=true pour voir les verrous)", 400)

    def gate(self, body: Locks, lk: dict, preview: dict):
        """Renvoie la réponse de `dry_run`, ou None si l'écriture peut partir. Les refus (`blockers`) ne se lèvent jamais."""
        if body.dry_run:
            return {"dry_run": True, **preview, "locks": lk, "phrase": PHRASE if lk["cut"] else None}
        if lk["blockers"]:
            self.refuse("Refusé : " + " ; ".join(lk["blockers"]), status.HTTP_409_CONFLICT)
        if lk["cut"] and not (body.acknowledge_cut_access and body.type_name == PHRASE):
            self.refuse("Coupure possible : " + " ; ".join(lk["cut"]) + f". Renvoie la requête avec acknowledge_cut_access=true et type_name=\"{PHRASE}\"", status.HTTP_409_CONFLICT)
        if lk["live"] and not body.acknowledge_guests:
            self.refuse("Machines concernées : " + " ; ".join(lk["live"]) + ". Renvoie la requête avec acknowledge_guests=true pour confirmer", status.HTTP_409_CONFLICT)
        return None


def _local(st: dict) -> dict | None:
    return next((n for n in st["nodes"] if n["local"]), None)


def _upid(raw) -> str | None:
    """Les tâches de Proxmox répondent un UPID ; autre chose n'est jamais recopié."""
    return raw if isinstance(raw, str) and raw.startswith("UPID:") and len(raw) < 300 else None


@router.post("/create")
async def create_cluster(body: CreateBody, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                         user: AdminUser = Depends(current_user)):
    """Crée un cluster à partir du nœud ISOLÉ que la connexion désigne. Refusé s'il est déjà dans un cluster."""
    c = Ctx(db, factory, conn_id, user, "cluster-create", body.clustername)
    c.need_confirm(body)
    st = shape_cluster(await c.px("get", "/cluster/status"))
    here = _local(st)
    blockers = [f"ce nœud fait déjà partie du cluster « {st['name']} » : un nœud ne peut créer un cluster que s'il est isolé"] if st["clustered"] else []
    lk = {"blockers": blockers, "cut": [], "live": []}
    params = build_create(body)
    out = c.gate(body, lk, {"node": here["name"] if here else None, "params": params})
    if out:
        return out
    upid = _upid(await c.px("post", "/cluster/config", **params))
    c.log("started", f"création demandée sur {here['name'] if here else '?'} ; liens : {len(body.links)}")
    return {"created": body.clustername, "node": here["name"] if here else None, "upid": upid, "locks": lk}


@router.post("/join")
async def join_cluster(body: JoinBody, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                       user: AdminUser = Depends(current_user)):
    """Fait rejoindre un cluster existant au nœud ISOLÉ que la connexion désigne. Sa configuration est REMPLACÉE par celle du cluster : la connexion de Kaji à ce nœud ne marchera plus."""
    c = Ctx(db, factory, conn_id, user, "cluster-join", body.hostname)
    c.need_confirm(body)
    st = shape_cluster(await c.px("get", "/cluster/status"))
    here = _local(st)
    guests = shape_guests(await c.px("get", "/cluster/resources", type="vm"))
    blockers = []
    if st["clustered"]:
        blockers.append(f"ce nœud fait déjà partie du cluster « {st['name']} » : un nœud ne peut en rejoindre un autre que s'il est isolé")
    if guests:
        blockers.append(f"ce nœud héberge {len(guests)} machine(s) : Proxmox refuse de rejoindre un cluster tant qu'il en porte (déplace-les ou sauvegarde-les, puis supprime-les du nœud)")
    if here and body.hostname.lower().rstrip(".") in {n.lower() for n in (here["name"], here["ip"]) if n}:
        blockers.append("l'adresse à contacter est celle de ce nœud lui-même")
    lk = {"blockers": blockers,
          "cut": ["la configuration de ce nœud (/etc/pve : utilisateurs, jetons, stockages) est REMPLACÉE par celle du cluster et ses services redémarrent : "
                  "la connexion de Kaji à ce nœud, et son jeton, ne marcheront plus"],
          "live": []}
    params = build_join(body)
    out = c.gate(body, lk, {"node": here["name"] if here else None, "params": {**params, "password": "défini (jamais affiché)"}})
    if out:
        return out
    upid = _upid(await c.px("post", "/cluster/config/join", password=body.password.get_secret_value(), **params))
    c.log("started", f"jonction demandée vers {body.hostname} ; mot de passe : défini ; liens : {len(body.links)}")
    return {"joining": here["name"] if here else None, "via": body.hostname, "upid": upid, "locks": lk}


@router.delete("/nodes/{node}")
async def remove_node(conn_id: int, node: str = Path(pattern=NODE.pattern), name: str | None = Query(default=None, max_length=63, description="Nom du nœud, retapé"),
                      confirm: bool = Query(default=False), acknowledge_cut_access: bool = Query(default=False), acknowledge_guests: bool = Query(default=False),
                      type_name: str | None = Query(default=None, max_length=40), dry_run: bool = Query(default=False),
                      db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Retire de la configuration du cluster un nœud HORS LIGNE (éteint pour de bon : il ne doit jamais revenir avec son ancienne configuration)."""
    body = Locks(confirm=confirm, acknowledge_cut_access=acknowledge_cut_access, acknowledge_guests=acknowledge_guests, type_name=type_name, dry_run=dry_run)
    c = Ctx(db, factory, conn_id, user, "cluster-remove-node", node)
    c.need_confirm(body)
    if not dry_run and name != node:
        c.refuse("Retape le nom du nœud à retirer pour confirmer", 400)
    st = shape_cluster(await c.px("get", "/cluster/status"))
    if not st["clustered"]:
        c.refuse("Ce nœud n'est pas dans un cluster", status.HTTP_409_CONFLICT)
    corosync = shape_corosync_nodes(await c.px("get", "/cluster/config/nodes"))
    target = next((n for n in st["nodes"] if n["name"] == node), None)
    if target is None and not any(n["name"] == node for n in corosync):
        c.refuse("Nœud inconnu de ce cluster", status.HTTP_404_NOT_FOUND)
    guests = [g for g in shape_guests(await c.px("get", "/cluster/resources", type="vm")) if g["node"] == node]
    protected = sorted(str(g["vmid"]) for g in guests if g["vmid"] in get_settings().protected_vmids)
    if protected:
        c.refuse(f"Machine protégée (KAJI_PROTECTED_VMIDS) : {', '.join(protected)} est configurée sur ce nœud ; il ne peut pas être retiré depuis Kaji, même confirmé", status.HTTP_403_FORBIDDEN)
    ha_note = []
    try:
        sids = {r["sid"] for r in shape_ha_resources(await _px(db, factory, conn_id, "get", "/cluster/ha/resources"))}
        ha_note = sorted(f"{'vm' if g['type'] == 'qemu' else 'ct'}:{g['vmid']}" for g in guests if f"{'vm' if g['type'] == 'qemu' else 'ct'}:{g['vmid']}" in sids)
    except HTTPException:
        ha_note = []                                                     # HA illisible (droit manquant) : l'aperçu ne dit simplement rien de plus
    blockers = []
    if target is not None and target["local"]:
        blockers.append("c'est le nœud auquel Kaji est connecté : retire-le depuis un autre membre du cluster (une autre connexion)")
    if target is not None and target["online"] is None:
        blockers.append("l'état (en ligne ou non) du nœud est inconnu : Kaji refuse de le retirer sans en être sûr")
    if target is not None and target["online"]:
        blockers.append("le nœud est EN LIGNE : éteins-le d'abord, pour de bon (il ne doit jamais revenir avec son ancienne configuration)")
    if st["quorate"] is not True:
        blockers.append("le cluster n'a pas le quorum : Proxmox ne peut pas écrire sa configuration")
    lk = {"blockers": blockers, **remove_locks(nodes_after=len(st["nodes"]) - 1, guests=[f"{g['vmid']}" for g in guests])}
    out = c.gate(body, lk, {"node": node, "guests": [g["vmid"] for g in guests], "ha_resources": ha_note})
    if out:
        return out
    await c.px("delete", f"/cluster/config/nodes/{node}")
    still = any(n["name"] == node for n in shape_corosync_nodes(await c.px("get", "/cluster/config/nodes")))
    if still:
        c.refuse("Proxmox n'a pas retiré le nœud", status.HTTP_502_BAD_GATEWAY)
    c.log("started", f"nœud retiré ; machines restées configurées : {len(guests)} ; ressources HA concernées : {len(ha_note)}")
    return {"removed": node, "guests": [g["vmid"] for g in guests], "ha_resources": ha_note, "locks": lk}
