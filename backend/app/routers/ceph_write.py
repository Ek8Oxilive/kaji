"""Ceph, ÉCRITURE : créer et modifier un pool (lot C2). Pas de suppression ici (lot C4), pas de pool à effacement.

Chaque écriture est auditée (succès, refus, erreur), exige une session, et ne part vers Proxmox qu'après les garde-fous du
cadrage (`docs/m12-ceph.md` §3). RIEN de tout cela n'a été validé sur un vrai Ceph.
"""
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from .. import audit
from ..cephspec import shape_pools, shape_rules, shape_status
from ..cephwrite import (POOL_NAME, RISKY, PoolCreate, PoolUpdate, changes_of, create_params, create_risks, update_params, update_risks,
                         write_slot)
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from .auth import current_user
from .ceph import NodeQ, _NotInstalled, _get, _on_node
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}/ceph", tags=["ceph-write"], dependencies=[Depends(current_user)])

NOT_INSTALLED_409 = "Ceph n'est pas installé sur ce cluster : rien à modifier"


def _recorder(db, user, conn_id, action, target):
    def log(st, detail=None, upid=None):
        audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target, status=st, detail=detail, upid=upid)

    def refuse(msg, code):
        log("error", msg)
        raise HTTPException(code, msg)

    return log, refuse


async def _health(db, factory, conn_id) -> str:
    return shape_status(await _get(db, factory, conn_id, "/cluster/ceph/status"))["health"]["status"]


async def _rules(db, factory, conn_id, node) -> set[str]:
    """Les règles CRUSH que Proxmox connaît : `crush_rule` doit en faire partie. Illisible : on refuse (502), on ne devine pas."""
    return {r["name"] for r in shape_rules(await _get(db, factory, conn_id, f"/nodes/{node}/ceph/rules"))}


@router.post("/pools", status_code=202)
async def create_pool(body: PoolCreate, conn_id: int, node: str | None = NodeQ, db: Session = Depends(get_db),
                      factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Crée un pool répliqué. Refusé si la santé est `HEALTH_ERR` ou inconnue, si le pool existe, si la règle CRUSH est
    inconnue. `size` et `min_size` valent au moins 2 (un seul exemplaire des données est refusé)."""
    log, refuse = _recorder(db, user, conn_id, "ceph-pool-create", f"pool/{body.name}")
    base = f"size={body.size} min_size={body.min_size} pg_num={body.pg_num} autoscale={body.autoscale} application={body.application}" \
           + (f" règle={body.crush_rule}" if body.crush_rule else "") + (" + stockage" if body.add_storage else "")

    async def read(fn):
        try:
            return await fn()
        except _NotInstalled:
            refuse(NOT_INSTALLED_409, 409)
        except HTTPException as e:
            log("error", f"{base} · {e.detail}")
            raise

    with write_slot(conn_id):
        health = await read(lambda: _health(db, factory, conn_id))
        if health not in ("HEALTH_OK", "HEALTH_WARN"):
            refuse(f"Ceph n'est pas dans un état sûr ({health}) : la création d'un pool est refusée", 409)
        n, r = await read(lambda: _on_node(db, factory, conn_id, node, {"main": "pool"}))
        if body.name in {p["name"] for p in shape_pools(r["main"])}:
            refuse(f"Le pool « {body.name} » existe déjà", 409)
        if body.crush_rule and body.crush_rule not in await read(lambda: _rules(db, factory, conn_id, n)):
            refuse("Règle CRUSH inconnue pour ce cluster", 422)
        risks = create_risks(body)
        if risks and not body.confirm:
            refuse("Confirmation requise (renvoie la requête avec confirm=true) : " + " ; ".join(risks), 400)
        try:
            upid = await _px(db, factory, conn_id, "post", f"/nodes/{n}/ceph/pool", **create_params(body))
        except HTTPException as e:
            log("error", f"{base} · {e.detail}")
            raise
        log("started", base, upid=upid if isinstance(upid, str) else None)
    return {"upid": upid if isinstance(upid, str) else None, "node": n, "pool": body.name}


@router.put("/pools/{pool}")
async def update_pool(body: PoolUpdate, conn_id: int, pool: str = Path(pattern=f"^{POOL_NAME.pattern}$"), node: str | None = NodeQ,
                      db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Modifie un pool. Changer `size`, `min_size`, `pg_num` ou `crush_rule` déplace ou duplique des données : refusé tant que la
    santé n'est pas `HEALTH_OK`, et exige `confirm=true`. Les autres réglages (autoscaler, application) passent sans cela."""
    log, refuse = _recorder(db, user, conn_id, "ceph-pool-update", f"pool/{pool}")
    base = "demande : " + " ".join(f"{k}={v}" for k, v in sorted(body.model_dump(exclude={"confirm"}, exclude_unset=True).items()))

    async def read(fn):
        try:
            return await fn()
        except _NotInstalled:
            refuse(NOT_INSTALLED_409, 409)
        except HTTPException as e:
            log("error", f"{base} · {e.detail}")
            raise

    with write_slot(conn_id):
        n, r = await read(lambda: _on_node(db, factory, conn_id, node, {"main": "pool"}))
        current = next((p for p in shape_pools(r["main"]) if p["name"] == pool), None)
        if current is None:
            refuse("Pool introuvable", 404)
        changes = changes_of(body, current)
        if not changes:
            refuse("Aucun changement : ces valeurs sont déjà celles du pool", 400)
        if current["type"] == "erasure" and ("size" in changes or "crush_rule" in changes):
            refuse("Sur un pool à effacement, size et la règle CRUSH ne peuvent pas être modifiés", 409)
        size = changes.get("size", current["size"])
        min_size = changes.get("min_size", current["min_size"])
        if size is not None and min_size is not None and min_size > size:
            refuse(f"min_size ({min_size}) ne peut pas dépasser size ({size})", 409)
        risky = [k for k in RISKY if k in changes]
        if risky:
            health = await read(lambda: _health(db, factory, conn_id))
            if health != "HEALTH_OK":
                refuse(f"Ceph n'est pas en bonne santé ({health}) : cette modification est refusée tant que la santé n'est pas HEALTH_OK", 409)
        if "crush_rule" in changes and changes["crush_rule"] not in await read(lambda: _rules(db, factory, conn_id, n)):
            refuse("Règle CRUSH inconnue pour ce cluster", 422)
        if risky and not body.confirm:
            refuse("Confirmation requise (renvoie la requête avec confirm=true) : " + " ; ".join(update_risks(changes, current)), 400)
        try:
            upid = await _px(db, factory, conn_id, "put", f"/nodes/{n}/ceph/pool/{pool}", **update_params(changes))
        except HTTPException as e:
            log("error", f"{base} · {e.detail}")
            raise
        log("started", "modifié : " + " ".join(f"{k}={v}" for k, v in sorted(changes.items())), upid=upid if isinstance(upid, str) else None)
    return {"upid": upid if isinstance(upid, str) else None, "node": n, "pool": pool, "changes": changes}

