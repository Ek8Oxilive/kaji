"""Ceph, DESTRUCTION : pool, OSD, moniteur, gestionnaire, MDS (lot C4). Règles : `app/cephdestroy.py`.

Chaque route : session, une seule écriture Ceph à la fois, état relu chez Proxmox, refus qu'aucune confirmation ne lève (`blockers`), puis `confirm=true` ET le nom exact retapé
(`name`), audit de chaque cas. `dry_run=true` montre refus et risques sans rien écrire. Pas de CephFS : le schéma de Proxmox n'a pas de `DELETE` pour cela.
RIEN de tout cela n'a été validé sur un vrai Ceph (le cluster réel n'en a pas).
"""
import re

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..cephdestroy import mds_plan, mgr_plan, mon_plan, osd_plan, pool_plan
from ..cephservices import SERVICE_NAME
from ..cephspec import shape_fs, shape_mgrs, shape_mons, shape_osds, shape_pools, shape_status
from ..cephwrite import POOL_NAME, write_slot
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from .actions import NODE
from .auth import current_user
from .ceph import NodeQ, _on_node
from .ceph_services import _Op
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}/ceph", tags=["ceph-destroy"], dependencies=[Depends(current_user)])
STORAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-_.]{0,63}")
NodeP = Path(pattern=NODE)


def NameP():
    """Un objet `Path` PAR paramètre : FastAPI y garde le nom du premier paramètre qui s'en sert (le partager casse les routes dont le paramètre porte un autre nom)."""
    return Path(pattern=f"^{SERVICE_NAME.pattern}$")


NameQ = Query(default=None, max_length=64, description="Nom exact de ce qui est détruit, retapé")


class _Destroy(_Op):
    async def status(self) -> dict:
        return shape_status(await self.get("/cluster/ceph/status"))

    async def filesystems(self, node: str) -> list[dict]:
        return shape_fs(await self.get(f"/nodes/{node}/ceph/fs"), [])["filesystems"]

    async def finish(self, blockers: list[str], risks: list[str], *, dry_run: bool, confirm: bool, name: str | None, expected: str, path: str, preview: dict | None = None, **params):
        """Aperçu, refus, confirmation, nom retapé, puis la suppression. Rien ne part avant que tout soit en règle."""
        if dry_run:
            return JSONResponse({"dry_run": True, "blockers": blockers, "risks": risks, "expected_name": expected, **(preview or {})}, status_code=200)    # un aperçu n'est pas « accepté » (202)
        if blockers:
            self.refuse("Refusé : " + " ; ".join(blockers), 409)
        self.confirm(confirm, risks)
        if name != expected:
            self.refuse(f"Le nom retapé ne correspond pas : retape exactement {expected}", 400)
        try:
            upid = await _px(self.db, self.factory, self.conn_id, "delete", path, **params)
        except HTTPException as e:
            self.log("error", f"{self.base} · {e.detail}")
            raise
        upid = upid if isinstance(upid, str) else None
        self.log("started", self.base, upid=upid)
        return {"upid": upid, "node": self.node}


@router.delete("/pools/{pool}", status_code=202)
async def destroy_pool(conn_id: int, pool: str = Path(pattern=f"^{POOL_NAME.pattern}$"), node: str | None = NodeQ, name: str | None = NameQ, confirm: bool = Query(default=False),
                       remove_storages: bool = Query(default=False), dry_run: bool = Query(default=False), db: Session = Depends(get_db),
                       factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Détruit un pool et TOUTES ses données. Refusé tant que la santé n'est pas HEALTH_OK, qu'un CephFS ou un volume de machine l'utilise, ou qu'un stockage Proxmox le référence
    (sauf `remove_storages=true`, qui le retire avec lui). `force` de Proxmox n'existe pas ici."""
    op = _Destroy(db, factory, conn_id, user, "ceph-pool-destroy", f"pool/{pool}", f"destruction du pool {pool}" + (" + stockages" if remove_storages else ""), node or "")
    with write_slot(conn_id):
        n, r = await op.read(lambda: _on_node(db, factory, conn_id, node, {"main": "pool"}))
        op.node = n
        current = next((p for p in shape_pools(r["main"]) if p["name"] == pool), None)
        if current is None:
            op.refuse("Pool introuvable", 404)
        health = (await op.status())["health"]["status"]
        filesystems = await op.filesystems(n)
        raw = await op.read(lambda: _px(db, factory, conn_id, "get", "/storage"))
        storages = [{"storage": s["storage"]} for s in (raw if isinstance(raw, list) else [])
                    if isinstance(s, dict) and s.get("type") == "rbd" and s.get("pool") == pool and isinstance(s.get("storage"), str) and STORAGE.fullmatch(s["storage"])]
        volumes: dict[str, list[dict] | None] = {}
        for s in storages:
            try:
                content = await _px(db, factory, conn_id, "get", f"/nodes/{n}/storage/{s['storage']}/content")
            except HTTPException:
                volumes[s["storage"]] = None
                continue
            volumes[s["storage"]] = [{"vmid": v.get("vmid") if isinstance(v.get("vmid"), int) and not isinstance(v.get("vmid"), bool) else None}
                                     for v in (content if isinstance(content, list) else []) if isinstance(v, dict)]
        blockers, risks = pool_plan(current, health, filesystems, storages, volumes, remove_storages)
        return await op.finish(blockers, risks, dry_run=dry_run, confirm=confirm, name=name, expected=pool, path=f"/nodes/{n}/ceph/pool/{pool}",
                               preview={"node": n, "pool": pool, "storages": [s["storage"] for s in storages]}, remove_storages=1 if remove_storages else 0)


@router.delete("/nodes/{node}/osds/{osd_id}", status_code=202)
async def destroy_osd(conn_id: int, osd_id: int = Path(ge=0, le=100000), node: str = NodeP, name: str | None = NameQ, confirm: bool = Query(default=False),
                      cleanup: bool = Query(default=False), dry_run: bool = Query(default=False), db: Session = Depends(get_db),
                      factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Détruit un OSD. Il doit être DEHORS, ARRÊTÉ, ne plus porter aucun groupe de placement, et Ceph doit être HEALTH_OK et « active+clean ».
    `cleanup=true` efface en plus la table de partitions du disque."""
    op = _Destroy(db, factory, conn_id, user, "ceph-osd-destroy", f"osd/{osd_id}", f"destruction de osd.{osd_id}" + (" + cleanup du disque" if cleanup else ""), node)
    with write_slot(conn_id):
        await op.node_online()
        osds = shape_osds(await op.get(f"/nodes/{node}/ceph/osd"))["osds"]
        target = next((o for o in osds if o["id"] == osd_id), None)
        if target is None:
            op.refuse("OSD introuvable", 404)
        if target["host"] != node:
            op.refuse(f"Cet OSD est sur « {target['host']} », pas sur « {node} »" if target["host"] else "L'hôte de cet OSD est illisible", 409)
        st = await op.status()
        blockers, risks = osd_plan(target, st["health"]["status"], st["pgs"]["all_clean"], cleanup)
        return await op.finish(blockers, risks, dry_run=dry_run, confirm=confirm, name=name, expected=f"osd.{osd_id}", path=f"/nodes/{node}/ceph/osd/{osd_id}",
                               preview={"node": node, "osd": osd_id}, cleanup=1 if cleanup else 0)


@router.delete("/nodes/{node}/monitors/{mon}", status_code=202)
async def destroy_monitor(conn_id: int, mon: str = NameP(), node: str = NodeP, name: str | None = NameQ, confirm: bool = Query(default=False), dry_run: bool = Query(default=False),
                          db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Détruit un moniteur (Proxmox détruit aussi le gestionnaire du même nom). Refusé s'il est le dernier, si le quorum serait perdu ou si la santé n'est pas HEALTH_OK."""
    op = _Destroy(db, factory, conn_id, user, "ceph-mon-destroy", f"mon/{mon}", f"destruction du moniteur {mon}", node)
    with write_slot(conn_id):
        await op.node_online()
        mons = shape_mons(await op.get(f"/nodes/{node}/ceph/mon"))
        target = next((m for m in mons if m["name"] == mon), None)
        if target is None:
            op.refuse("Moniteur introuvable", 404)
        if target["host"] != node:
            op.refuse(f"Ce moniteur est sur « {target['host']} », pas sur « {node} »" if target["host"] else "L'hôte de ce moniteur est illisible", 409)
        mgrs = shape_mgrs(await op.get(f"/nodes/{node}/ceph/mgr"))
        twin = next((m for m in mgrs if m["name"] == mon), None)
        last_mgr = twin is not None and twin.get("state") in ("active", "standby") and not any(m is not twin and m.get("state") in ("active", "standby") for m in mgrs)
        blockers, risks = mon_plan(target, mons, (await op.status())["health"]["status"], last_mgr)
        return await op.finish(blockers, risks, dry_run=dry_run, confirm=confirm, name=name, expected=mon, path=f"/nodes/{node}/ceph/mon/{mon}", preview={"node": node, "monitor": mon})


@router.delete("/nodes/{node}/managers/{mgr}", status_code=202)
async def destroy_manager(conn_id: int, mgr: str = NameP(), node: str = NodeP, name: str | None = NameQ, confirm: bool = Query(default=False), dry_run: bool = Query(default=False),
                          db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Détruit un gestionnaire. Refusé si Ceph est en erreur ; confirmation renforcée si c'est le dernier."""
    op = _Destroy(db, factory, conn_id, user, "ceph-mgr-destroy", f"mgr/{mgr}", f"destruction du gestionnaire {mgr}", node)
    with write_slot(conn_id):
        await op.node_online()
        mgrs = shape_mgrs(await op.get(f"/nodes/{node}/ceph/mgr"))
        target = next((m for m in mgrs if m["name"] == mgr), None)
        if target is None:
            op.refuse("Gestionnaire introuvable", 404)
        if target["host"] != node:
            op.refuse(f"Ce gestionnaire est sur « {target['host']} », pas sur « {node} »" if target["host"] else "L'hôte de ce gestionnaire est illisible", 409)
        blockers, risks = mgr_plan(target, mgrs, (await op.status())["health"]["status"])
        return await op.finish(blockers, risks, dry_run=dry_run, confirm=confirm, name=name, expected=mgr, path=f"/nodes/{node}/ceph/mgr/{mgr}", preview={"node": node, "manager": mgr})


@router.delete("/nodes/{node}/mds/{mds}", status_code=202)
async def destroy_mds(conn_id: int, mds: str = NameP(), node: str = NodeP, name: str | None = NameQ, confirm: bool = Query(default=False), dry_run: bool = Query(default=False),
                      db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Détruit un serveur de métadonnées. Refusé si Ceph est en erreur, ou si c'est le SEUL MDS alors qu'un CephFS existe."""
    op = _Destroy(db, factory, conn_id, user, "ceph-mds-destroy", f"mds/{mds}", f"destruction du MDS {mds}", node)
    with write_slot(conn_id):
        await op.node_online()
        fsx = shape_fs(await op.get(f"/nodes/{node}/ceph/fs"), await op.get(f"/nodes/{node}/ceph/mds"))
        target = next((m for m in fsx["mds"] if m["name"] == mds), None)
        if target is None:
            op.refuse("MDS introuvable", 404)
        if target["host"] != node:
            op.refuse(f"Ce MDS est sur « {target['host']} », pas sur « {node} »" if target["host"] else "L'hôte de ce MDS est illisible", 409)
        blockers, risks = mds_plan(target, fsx["mds"], fsx["filesystems"], (await op.status())["health"]["status"])
        return await op.finish(blockers, risks, dry_run=dry_run, confirm=confirm, name=name, expected=mds, path=f"/nodes/{node}/ceph/mds/{mds}", preview={"node": node, "mds": mds})
