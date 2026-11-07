"""Dépôts apt d'un nœud : activer / désactiver, ajouter un dépôt standard (droit `Sys.Modify`). Garde-fous : `repospec`."""
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..repospec import RepoAdd, RepoToggle, find_repo, risks_add, risks_toggle, verdict
from ..systemspec import shape_repositories
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["node-repos"], dependencies=[Depends(current_user)])


async def _fresh(db, factory, conn_id: int, node: str) -> dict:
    return shape_repositories(await _px(db, factory, conn_id, "get", f"/nodes/{node}/apt/repositories"))


async def _subscribed(db, factory, conn_id: int, node: str) -> bool:
    try:
        sub = await _px(db, factory, conn_id, "get", f"/nodes/{node}/subscription")
    except HTTPException:
        return False                                  # illisible : on suppose « sans abonnement » (plus prudent)
    return isinstance(sub, dict) and sub.get("status") == "active"


async def _apply(db, factory, user, conn_id, node, action, target, plan, method, params):
    def fail(code: int, msg: str):
        audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target, status="error", detail=msg)
        raise HTTPException(code, msg)

    try:
        fresh = await _fresh(db, factory, conn_id, node)
        refused = await plan(fresh)
    except HTTPException:
        fail(502, "Dépôts illisibles : action refusée par précaution")
    if refused:
        fail(*refused)
    try:
        await _px(db, factory, conn_id, method, f"/nodes/{node}/apt/repositories", **params)
    except HTTPException as e:
        fail(e.status_code, str(e.detail))
    audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target, status="ok")
    return {"ok": True}


@router.put("/nodes/{node}/apt/repositories")
async def toggle_repo(body: RepoToggle, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
                      factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Active ou désactive un dépôt existant (identifié par son fichier et sa position, relus chez Proxmox)."""
    async def plan(fresh):
        repo = find_repo(fresh["files"], body.path, body.index)
        if repo is None:
            return 404, "Dépôt introuvable"
        if repo["enabled"] == body.enabled:
            return 409, "Le dépôt est déjà dans cet état"
        risks = risks_toggle(fresh["files"], body.path, body.index, body.enabled, await _subscribed(db, factory, conn_id, node))
        return verdict(body.digest, fresh, body.confirm, body.accept_risk, risks)
    return await _apply(db, factory, user, conn_id, node, "apt-repo-toggle", f"node/{node}:{body.path}#{body.index}", plan, "put",
                        {"path": body.path, "index": body.index, "enabled": int(body.enabled), "digest": body.digest})


@router.post("/nodes/{node}/apt/repositories")
async def add_repo(body: RepoAdd, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
                   factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Ajoute un dépôt standard de Proxmox (parmi ceux que Proxmox propose et qui ne sont pas encore configurés)."""
    async def plan(fresh):
        std = next((s for s in fresh["standard"] if s["handle"] == body.handle), None)
        if std is None:
            return 404, "Dépôt standard inconnu"
        if std["status"] is not None:
            return 409, "Ce dépôt est déjà configuré : active-le au lieu de l'ajouter"
        return verdict(body.digest, fresh, body.confirm, body.accept_risk, risks_add(body.handle, await _subscribed(db, factory, conn_id, node)))
    return await _apply(db, factory, user, conn_id, node, "apt-repo-add", f"node/{node}:{body.handle}", plan, "post",
                        {"handle": body.handle, "digest": body.digest})
