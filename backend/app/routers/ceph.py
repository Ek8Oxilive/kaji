"""Ceph en LECTURE SEULE : état et santé, moniteurs, gestionnaires, OSD, pools, CephFS, configuration, journal.

Aucune écriture, aucune route autre que GET. Si Ceph n'est pas installé (Proxmox répond 500 « binary not installed »), la
réponse est un 200 clair `{"installed": false, "message": …}` et non une erreur brute.
"""
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..cephspec import (shape_conf_db, shape_conf_raw, shape_fs, shape_log, shape_mgrs, shape_mons, shape_osds,
                        shape_pools, shape_rules, shape_status)
from ..db import get_db
from ..deps import get_client_factory
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px, http_error
from .connections import _get_or_404, _params

router = APIRouter(prefix="/api/connections/{conn_id}/ceph", tags=["ceph"], dependencies=[Depends(current_user)])

NOT_INSTALLED = {"installed": False, "message": "Ceph n'est pas installé sur ce cluster."}
_NODE = re.compile(NODE)


class _NotInstalled(Exception):
    pass


def _says_not_installed(e: httpx.HTTPStatusError) -> bool:
    """Proxmox répond 500 « binary not installed: /usr/bin/ceph-mon ». On cherche le message dans la phrase de statut ET
    dans le corps : on ne sait pas lequel des deux le porte, et le texte brut n'est jamais renvoyé à l'utilisateur."""
    if e.response.status_code != 500:
        return False
    try:
        body = e.response.text
    except Exception:  # noqa: BLE001 — un corps illisible ne doit pas masquer l'erreur d'origine
        body = ""
    return "not installed" in f"{e.response.reason_phrase} {body}".lower()


async def _get(db: Session, factory: Factory, conn_id: int, path: str, **params):
    client = factory(**_params(_get_or_404(db, conn_id)))
    try:
        return await client.get(path, **params)
    except httpx.HTTPStatusError as e:
        if _says_not_installed(e):
            raise _NotInstalled from e
        raise http_error(e)
    except httpx.HTTPError as e:
        raise http_error(e)
    finally:
        await client.aclose()


async def _candidates(db: Session, factory: Factory, conn_id: int, node: str | None) -> list[str]:
    """`?node=` si fourni ; sinon les nœuds en ligne, par ordre alphabétique (Ceph peut ne pas être sur tous)."""
    if node:
        return [node]
    data = await _px(db, factory, conn_id, "get", "/nodes")
    names = sorted(n["node"] for n in data if isinstance(n, dict) and n.get("status") == "online"
                   and isinstance(n.get("node"), str) and _NODE.fullmatch(n["node"])) if isinstance(data, list) else []
    if not names:
        raise HTTPException(503, "Aucun nœud en ligne pour interroger Ceph")
    return names


async def _on_node(db, factory, conn_id, node, calls: dict[str, str], **params):
    """Interroge les nœuds tour à tour (le premier qui a Ceph répond). `calls` : nom -> chemin sous `/nodes/{n}/ceph/`.
    Renvoie `(nœud, {nom: données})` ou lève `_NotInstalled` si aucun nœud n'a Ceph."""
    for n in await _candidates(db, factory, conn_id, node):
        try:
            return n, {k: await _get(db, factory, conn_id, f"/nodes/{n}/ceph/{p}", **(params if k == "main" else {}))
                       for k, p in calls.items()}
        except _NotInstalled:
            continue
    raise _NotInstalled


NodeQ = Query(default=None, pattern=NODE, description="Nœud à interroger ; sinon les nœuds en ligne, tour à tour")


@router.get("/status")
async def ceph_status(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Santé et état du cluster Ceph (`ceph -s`). Lecture seule."""
    try:
        return {"installed": True, **shape_status(await _get(db, factory, conn_id, "/cluster/ceph/status"))}
    except _NotInstalled:
        return NOT_INSTALLED


@router.get("/monitors")
async def ceph_monitors(conn_id: int, node: str | None = NodeQ, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    try:
        n, r = await _on_node(db, factory, conn_id, node, {"main": "mon"})
        return {"installed": True, "node": n, "monitors": shape_mons(r["main"])}
    except _NotInstalled:
        return NOT_INSTALLED


@router.get("/managers")
async def ceph_managers(conn_id: int, node: str | None = NodeQ, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    try:
        n, r = await _on_node(db, factory, conn_id, node, {"main": "mgr"})
        return {"installed": True, "node": n, "managers": shape_mgrs(r["main"])}
    except _NotInstalled:
        return NOT_INSTALLED


@router.get("/osds")
async def ceph_osds(conn_id: int, node: str | None = NodeQ, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """OSD à plat (état, usage, classe de disque) avec leur hôte, les drapeaux du cluster et un résumé."""
    try:
        n, r = await _on_node(db, factory, conn_id, node, {"main": "osd"})
        return {"installed": True, "node": n, **shape_osds(r["main"])}
    except _NotInstalled:
        return NOT_INSTALLED


@router.get("/pools")
async def ceph_pools(conn_id: int, node: str | None = NodeQ, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Pools et leurs réglages de redondance. Les avertissements signalent un réglage dangereux, sans rien modifier."""
    try:
        n, r = await _on_node(db, factory, conn_id, node, {"main": "pool"})
        return {"installed": True, "node": n, "pools": shape_pools(r["main"])}
    except _NotInstalled:
        return NOT_INSTALLED


@router.get("/rules")
async def ceph_rules(conn_id: int, node: str | None = NodeQ, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Règles de placement CRUSH (lecture seule) : proposées, et vérifiées, à la création d'un pool."""
    try:
        n, r = await _on_node(db, factory, conn_id, node, {"main": "rules"})
        return {"installed": True, "node": n, "rules": shape_rules(r["main"])}
    except _NotInstalled:
        return NOT_INSTALLED


@router.get("/filesystems")
async def ceph_filesystems(conn_id: int, node: str | None = NodeQ, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """CephFS et leurs serveurs de métadonnées (MDS)."""
    try:
        n, r = await _on_node(db, factory, conn_id, node, {"fs": "fs", "mds": "mds"})
        return {"installed": True, "node": n, **shape_fs(r["fs"], r["mds"])}
    except _NotInstalled:
        return NOT_INSTALLED


@router.get("/config")
async def ceph_config(conn_id: int, node: str | None = NodeQ, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """`ceph.conf` et base de configuration, en lecture seule, secrets masqués. Aucune édition possible."""
    try:
        n, r = await _on_node(db, factory, conn_id, node, {"raw": "cfg/raw"})
        unavailable: list[str] = []
        try:
            entries = shape_conf_db(await _get(db, factory, conn_id, f"/nodes/{n}/ceph/cfg/db"))
        except (_NotInstalled, HTTPException):
            entries, unavailable = [], ["db"]               # la base peut être illisible sans que le reste le soit : on le dit
        return {"installed": True, "node": n, "conf": shape_conf_raw(r["raw"]), "entries": entries, "unavailable": unavailable}
    except _NotInstalled:
        return NOT_INSTALLED


@router.get("/log")
async def ceph_log(conn_id: int, node: str | None = NodeQ, limit: int = Query(default=100, ge=1, le=500),
                   start: int = Query(default=0, ge=0, le=1_000_000_000),
                   db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Journal de Ceph, `limit` lignes à partir de `start` (secrets masqués)."""
    try:
        n, r = await _on_node(db, factory, conn_id, node, {"main": "log"}, start=start, limit=limit)
        return {"installed": True, "node": n, "lines": shape_log(r["main"])}
    except _NotInstalled:
        return NOT_INSTALLED
