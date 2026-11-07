"""Écriture sur les disques d'un nœud (droit `Sys.Modify`) : GPT, effacer, LVM, LVM-thin, répertoire, ZFS. Garde-fous : `diskwrite`.

L'état des disques est relu chez Proxmox à chaque action (fail closed). Les paramètres envoyés à Proxmox sont construits ici, champ par
champ, à partir de valeurs déjà validées : aucun champ libre n'est transmis. La suppression de volumes n'existe pas dans ce lot.
"""
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from .. import audit, diskspec as D
from ..db import get_db
from ..deps import get_client_factory
from ..diskdelete import DeleteBody, Kind, NAME as DNAME, delete_params, verdict as delete_verdict
from ..diskwrite import (DirectoryCreate, DiskOnly, LvmCreate, ZfsCreate, verdict_gpt, verdict_lvm, verdict_wipe, verdict_zfs)
from ..models import AdminUser
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["node-disks-write"], dependencies=[Depends(current_user)])


async def _disks(db, factory, conn_id: int, node: str) -> list[dict]:
    return D.shape_disks(await _px(db, factory, conn_id, "get", f"/nodes/{node}/disks/list", **{"include-partitions": 1}))


async def _existing(db, factory, conn_id: int, node: str, kind: str) -> set[str]:
    raw = await _px(db, factory, conn_id, "get", f"/nodes/{node}/disks/{kind}")
    if kind == "lvm":
        return {v["name"] for v in D.shape_lvm(raw)}
    if kind == "lvmthin":
        return {p["name"] for p in D.shape_lvmthin(raw)} | {p["vg"] for p in D.shape_lvmthin(raw) if p["vg"]}
    if kind == "directory":
        return {d["path"].rstrip("/").rsplit("/", 1)[-1] for d in D.shape_directories(raw)}
    return {z["name"] for z in D.shape_zfs(raw)}


async def _run(db, factory, user, conn_id, node, action, target, *, check, method, path, params):
    """Relit l'état, applique le verdict, écrit, audite. `check(disks)` renvoie `None` ou `(code, message)`."""
    def fail(code: int, msg: str):
        audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target, status="error", detail=msg)
        raise HTTPException(code, msg)

    try:
        refused = await check()
    except HTTPException:
        fail(502, "État des disques illisible : action refusée par précaution")
    if refused:
        fail(*refused)
    try:
        upid = await _px(db, factory, conn_id, method, path, **params)
    except HTTPException as e:
        fail(e.status_code, str(e.detail))
    audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target, status="started", upid=upid if isinstance(upid, str) else None)
    return {"upid": upid if isinstance(upid, str) else None, "node": node}


@router.post("/nodes/{node}/disks/initgpt", status_code=status.HTTP_202_ACCEPTED)
async def init_gpt(body: DiskOnly, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
                   factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    async def check():
        return verdict_gpt(body, await _disks(db, factory, conn_id, node))
    return await _run(db, factory, user, conn_id, node, "disk-initgpt", f"disk/{node}:{body.disk}", check=check, method="post",
                      path=f"/nodes/{node}/disks/initgpt", params={"disk": body.disk})


@router.post("/nodes/{node}/disks/wipe", status_code=status.HTTP_202_ACCEPTED)
async def wipe(body: DiskOnly, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
               factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    async def check():
        return verdict_wipe(body, await _disks(db, factory, conn_id, node))
    return await _run(db, factory, user, conn_id, node, "disk-wipe", f"disk/{node}:{body.disk}", check=check, method="put",
                      path=f"/nodes/{node}/disks/wipedisk", params={"disk": body.disk})


@router.post("/nodes/{node}/disks/lvm", status_code=status.HTTP_202_ACCEPTED)
async def create_lvm(body: LvmCreate, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
                     factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    async def check():
        return verdict_lvm(body, await _disks(db, factory, conn_id, node), await _existing(db, factory, conn_id, node, "lvm"))
    return await _run(db, factory, user, conn_id, node, "disk-lvm-create", f"lvm/{node}:{body.name}", check=check, method="post",
                      path=f"/nodes/{node}/disks/lvm", params={"name": body.name, "device": body.device, "add_storage": int(body.add_storage)})


@router.post("/nodes/{node}/disks/lvmthin", status_code=status.HTTP_202_ACCEPTED)
async def create_lvmthin(body: LvmCreate, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
                         factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    async def check():
        return verdict_lvm(body, await _disks(db, factory, conn_id, node), await _existing(db, factory, conn_id, node, "lvmthin"))
    return await _run(db, factory, user, conn_id, node, "disk-lvmthin-create", f"lvmthin/{node}:{body.name}", check=check, method="post",
                      path=f"/nodes/{node}/disks/lvmthin", params={"name": body.name, "device": body.device, "add_storage": int(body.add_storage)})


@router.post("/nodes/{node}/disks/directory", status_code=status.HTTP_202_ACCEPTED)
async def create_directory(body: DirectoryCreate, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
                           factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    async def check():
        return verdict_lvm(body, await _disks(db, factory, conn_id, node), await _existing(db, factory, conn_id, node, "directory"))
    return await _run(db, factory, user, conn_id, node, "disk-directory-create", f"directory/{node}:{body.name}", check=check, method="post",
                      path=f"/nodes/{node}/disks/directory",
                      params={"name": body.name, "device": body.device, "filesystem": body.filesystem, "add_storage": int(body.add_storage)})


@router.post("/nodes/{node}/disks/zfs", status_code=status.HTTP_202_ACCEPTED)
async def create_zfs(body: ZfsCreate, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
                     factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    async def check():
        return verdict_zfs(body, await _disks(db, factory, conn_id, node), await _existing(db, factory, conn_id, node, "zfs"))
    return await _run(db, factory, user, conn_id, node, "disk-zfs-create", f"zfs/{node}:{body.name}", check=check, method="post",
                      path=f"/nodes/{node}/disks/zfs",
                      params={"name": body.name, "devices": ",".join(body.devices), "raidlevel": body.raidlevel, "compression": body.compression,
                              "ashift": body.ashift, "add_storage": int(body.add_storage)})


# ---------------------------------------------------------------- supprimer un volume (vide)

def _storages(raw) -> list[dict] | None:
    """Configuration des stockages réduite aux champs utiles ; `None` si illisible."""
    if not isinstance(raw, list):
        return None
    keys = ("storage", "type", "vgname", "thinpool", "pool", "path")
    out = []
    for r in raw:
        if isinstance(r, dict) and isinstance(r.get("storage"), str):
            nodes = r.get("nodes")
            out.append({**{k: r.get(k) for k in keys}, "nodes": [n for n in nodes.split(",") if n] if isinstance(nodes, str) else None})
    return out


@router.post("/nodes/{node}/disks/{kind}/{name}/delete", status_code=status.HTTP_202_ACCEPTED)
async def delete_volume(body: DeleteBody, conn_id: int, node: str = Path(pattern=NODE), kind: Kind = Path(), name: str = Path(pattern=DNAME),
                        db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Supprime un groupe LVM, un pool LVM-thin, un répertoire ou un pool ZFS **vide**. Route POST (et non DELETE) parce qu'elle porte un corps."""
    async def check():
        st: dict = {"node": node, "disks": await _disks(db, factory, conn_id, node)}
        for k, shape in (("lvm", D.shape_lvm), ("lvmthin", D.shape_lvmthin), ("directory", D.shape_directories), ("zfs", D.shape_zfs)):
            st[k] = shape(await _px(db, factory, conn_id, "get", f"/nodes/{node}/disks/{k}"))
        st["storages"] = _storages(await _px(db, factory, conn_id, "get", "/storage"))
        st["contents"] = {}
        from ..diskdelete import matching_storages
        for s in matching_storages(kind, name, body.vg, st["storages"] or []):
            if s["nodes"] and node not in s["nodes"]:
                continue
            try:
                rows = await _px(db, factory, conn_id, "get", f"/nodes/{node}/storage/{s['storage']}/content")
                st["contents"][s["storage"]] = len(rows) if isinstance(rows, list) else None
            except HTTPException:
                st["contents"][s["storage"]] = None
        return delete_verdict(kind, name, body, st)
    return await _run(db, factory, user, conn_id, node, f"disk-{kind}-delete", f"{kind}/{node}:{name}", check=check, method="delete",
                      path=f"/nodes/{node}/disks/{kind}/{name}", params=delete_params(kind, body))
