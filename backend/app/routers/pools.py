"""Pools de ressources en écriture (Datacenter → Permissions → Pools), lot #298. La liste simple existe déjà (`GET /pools`, `create.py`).

Lecture : `GET /pools/overview` (tous les pools avec leurs membres) et `GET /pools/{poolid}`. Écriture : créer, modifier (commentaire, ajouter ou retirer des
machines et des stockages), supprimer.

Garde-fous : tout est relu chez Proxmox (existence du pool, des machines et des stockages, appartenance) AVANT d'écrire ; une machine de `KAJI_PROTECTED_VMIDS`
n'est jamais ajoutée, retirée ni déplacée ; retirer un membre ou déplacer une machine d'un autre pool exige `confirm` (les droits accordés PAR le pool changent) ;
supprimer exige `confirm` ET l'identifiant retapé, et n'est possible que pour un pool VIDE et SANS droit (ACL) posé sur `/pool/<id>`. `dry_run` : le plan, rien d'écrit.
Proxmox exige aussi « le droit de modifier les permissions » sur ce qu'on ajoute ou retire. RIEN n'a été validé en réel au moment du code.
"""
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..poolspec import PoolCreate, PoolUpdate, plan_calls, shape_pool, shape_pools
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(tags=["pools"], dependencies=[Depends(current_user)])
BASE = "/api/connections/{conn_id}/pools"
POOL_PATH = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,39}$")


async def _all_pools(db, factory, conn_id) -> list[dict]:
    """Tous les pools AVEC leurs membres. Constaté en réel (Proxmox 9.1.9) : `GET /pools` sans `poolid` ne renvoie PAS les membres ; il faut
    `GET /pools?poolid=…` pour chaque pool (une lecture de plus par pool, 100 pools au plus)."""
    listing = shape_pools(await _px(db, factory, conn_id, "get", "/pools"))[:100]
    out = []
    for p in listing:
        raw = await _px(db, factory, conn_id, "get", "/pools", poolid=p["poolid"])
        rows = raw if isinstance(raw, list) else [raw]
        out.append(next((d for d in shape_pools(rows) if d["poolid"] == p["poolid"]), p))
    return out


@router.get(BASE + "/overview")
async def pools_overview(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Tous les pools avec leurs membres (une seule lecture chez Proxmox)."""
    return await _all_pools(db, factory, conn_id)


@router.get(BASE + "/{poolid}")
async def pool_detail(conn_id: int, poolid: str = POOL_PATH, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    pool = next((p for p in await _all_pools(db, factory, conn_id) if p["poolid"] == poolid), None)
    if pool is None:
        raise HTTPException(404, "Pool introuvable")
    return pool


class _Ctx:
    """Journal d'audit, refus et appels Proxmox d'une écriture de pool (une instance par requête)."""

    def __init__(self, db, factory, conn_id, user, action, target):
        self.db, self.factory, self.conn_id, self.user, self.action, self.target = db, factory, conn_id, user, action, target

    def log(self, st, detail=None):
        audit.record(self.db, username=self.user.username, connection_id=self.conn_id, action=self.action, target=self.target, status=st, detail=detail)

    def refuse(self, msg: str, code: int, detail: str | None = None):
        self.log("error", detail or msg)
        raise HTTPException(code, msg)

    async def px(self, method: str, path: str, **kw):
        try:
            return await _px(self.db, self.factory, self.conn_id, method, path, **kw)
        except HTTPException as e:
            self.log("error", str(e.detail))
            raise


@router.post(BASE, status_code=status.HTTP_201_CREATED)
async def create_pool(body: PoolCreate, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                      user: AdminUser = Depends(current_user)):
    c = _Ctx(db, factory, conn_id, user, "pool-create", f"pool/{body.poolid}")
    if any(p["poolid"] == body.poolid for p in await _all_pools(db, factory, conn_id)):
        c.refuse("Un pool porte déjà cet identifiant", 409)
    params = {"poolid": body.poolid, **({"comment": body.comment} if body.comment else {})}
    await c.px("post", "/pools", **params)
    c.log("started", "créé" + (" avec un commentaire" if body.comment else ""))
    return {"poolid": body.poolid}


@router.put(BASE + "/{poolid}")
async def update_pool(body: PoolUpdate, conn_id: int, poolid: str = POOL_PATH, db: Session = Depends(get_db),
                      factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    c = _Ctx(db, factory, conn_id, user, "pool-update", f"pool/{poolid}")
    if msg := body.check():
        c.refuse(msg, 400 if msg.startswith("Aucune") else 422)
    pools = await _all_pools(db, factory, conn_id)
    pool = next((p for p in pools if p["poolid"] == poolid), None)
    if pool is None:
        c.refuse("Pool introuvable", 404)
    protected = get_settings().protected_vmids
    touched = {*body.add_vms, *body.remove_vms}
    if touched & protected:
        c.refuse("Une machine protégée par Kaji (KAJI_PROTECTED_VMIDS) ne peut pas être ajoutée, retirée ni déplacée", 409, "machine protégée")
    members_vms, members_sto = set(pool["vms"]), set(pool["storages"])
    other_pool = {v: p["poolid"] for p in pools if p["poolid"] != poolid for v in p["vms"]}
    if any(v not in members_vms for v in body.remove_vms) or any(s not in members_sto for s in body.remove_storage):
        c.refuse("Un élément à retirer n'appartient pas à ce pool", 409)
    if any(v in members_vms for v in body.add_vms) or any(s in members_sto for s in body.add_storage):
        c.refuse("Un élément à ajouter est déjà dans ce pool", 409)
    moving = [v for v in body.add_vms if v in other_pool]
    if moving and not body.allow_move:
        c.refuse("Une machine appartient déjà à un autre pool : renvoie la requête avec allow_move=true (elle y sera retirée)", 409)
    if body.add_vms:
        res = await c.px("get", "/cluster/resources", type="vm")
        known = {r.get("vmid") for r in res or [] if isinstance(r, dict)}
        if any(v not in known for v in body.add_vms):
            c.refuse("Une machine à ajouter est introuvable", 404)
    if body.add_storage:
        res = await c.px("get", "/storage")
        known_s = {r.get("storage") for r in res or [] if isinstance(r, dict)}
        if any(s not in known_s for s in body.add_storage):
            c.refuse("Un stockage à ajouter est introuvable", 404)
    reasons = []
    if body.remove_vms or body.remove_storage:
        reasons.append("retirer un membre peut retirer des droits d'accès accordés par ce pool")
    if moving:
        reasons.append("déplacer une machine la retire de son pool actuel (ses droits changent)")
    if reasons and not body.confirm and not body.dry_run:
        c.refuse("Confirmation requise (renvoie la requête avec confirm=true) : " + " ; ".join(reasons), 400)
    calls = plan_calls(poolid, body)
    if body.dry_run:
        return {"dry_run": True, "calls": calls, "needs_confirm": reasons}
    for call in calls:
        await c.px("put", "/pools", **call)
    after = next((p for p in await _all_pools(db, factory, conn_id) if p["poolid"] == poolid), None)
    c.log("started", f"+{len(body.add_vms)} machine(s), +{len(body.add_storage)} stockage(s), -{len(body.remove_vms)} machine(s), -{len(body.remove_storage)} stockage(s)"
          + (", commentaire" if body.comment is not None else "") + (", déplacement" if moving else ""))
    return {"changed": True, "pool": after}


@router.delete(BASE + "/{poolid}")
async def delete_pool(conn_id: int, poolid: str = POOL_PATH, confirm: bool = Query(default=False), name: str = Query(default="", max_length=64),
                      db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    c = _Ctx(db, factory, conn_id, user, "pool-delete", f"pool/{poolid}")
    if not confirm:
        c.refuse("Suppression d'un pool : renvoie la requête avec ?confirm=true et l'identifiant du pool (?name=)", 400)
    if name != poolid:
        c.refuse("L'identifiant retapé ne correspond pas : suppression refusée", 400)
    pool = next((p for p in await _all_pools(db, factory, conn_id) if p["poolid"] == poolid), None)
    if pool is None:
        c.refuse("Pool introuvable", 404)
    if pool["members"]:
        c.refuse(f"Le pool n'est pas vide ({len(pool['members'])} membre(s)) : retire d'abord ses machines et stockages", 409)
    try:
        acl = await _px(db, factory, conn_id, "get", "/access/acl")
    except HTTPException:
        acl = None
    if not isinstance(acl, list):
        c.refuse("Impossible de vérifier les droits (ACL) posés sur ce pool : suppression refusée", 502)
    if any(isinstance(a, dict) and a.get("path") == f"/pool/{poolid}" for a in acl):
        c.refuse("Des droits (ACL) sont posés sur ce pool : retire-les d'abord (page Accès), sinon des accès disparaîtraient avec lui", 409)
    await c.px("delete", "/pools", poolid=poolid)
    c.log("started", "supprimé")
    return {"deleted": poolid}

