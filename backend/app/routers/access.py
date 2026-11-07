"""Accès Proxmox (lecture seule) : utilisateurs, groupes, rôles, ACL, realms, et droits de Kaji."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..accessspec import (build_fixes, check_features, granted, needed_paths, shape_acl, shape_groups, shape_realms,
                          shape_roles, shape_users)
from ..db import get_db
from ..deps import get_client_factory
from .auth import current_user
from .connections import _get_or_404
from .cluster import Factory, _px_get

router = APIRouter(prefix="/api/connections/{conn_id}/access", tags=["access"], dependencies=[Depends(current_user)])


@router.get("/users")
async def users(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Utilisateurs visibles par le token. Lecture seule."""
    return shape_users(await _px_get(db, factory, conn_id, "/access/users"))


@router.get("/groups")
async def groups(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    return shape_groups(await _px_get(db, factory, conn_id, "/access/groups"))


@router.get("/roles")
async def roles(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Rôles et leurs privilèges."""
    return shape_roles(await _px_get(db, factory, conn_id, "/access/roles"))


@router.get("/acl")
async def acl(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """ACL visibles par le token (Proxmox ne montre que celles qu'il a le droit de voir)."""
    return shape_acl(await _px_get(db, factory, conn_id, "/access/acl"))


@router.get("/realms")
async def realms(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    return shape_realms(await _px_get(db, factory, conn_id, "/access/domains"))


async def _features(db: Session, factory: Factory, conn_id: int) -> list[dict]:
    """Évalue les droits de Kaji. Si Proxmox ne répond à aucune question, l'erreur est renvoyée telle quelle."""
    perms: dict[str, set[str] | None] = {}
    first_error: HTTPException | None = None
    for path in needed_paths():
        try:
            raw = await _px_get(db, factory, conn_id, "/access/permissions", path=path)
        except HTTPException as e:
            first_error = first_error or e
            perms[path] = None
            continue
        perms[path] = granted(raw.get(path)) if isinstance(raw, dict) else None
    if all(v is None for v in perms.values()) and first_error is not None:
        raise first_error
    return check_features(perms)


@router.get("/features")
async def features(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """« Droits de Kaji » : pour chaque fonction, le token a-t-il les privilèges nécessaires ? (`ok`, `missing` avec la liste
    des privilèges manquants, ou `unknown`). Les droits sont ceux que Proxmox calcule pour le token, héritage compris.
    Si Proxmox ne répond à aucune des questions, l'erreur est renvoyée telle quelle plutôt qu'un faux « inconnu »."""
    return await _features(db, factory, conn_id)


@router.get("/fixes")
async def fixes(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Commandes `pveum` à lancer **en root sur un nœud** pour corriger les droits manquants. **Kaji n'exécute rien** et
    n'obtient aucun droit de plus : ce sont des textes construits à partir de constantes et de l'utilisateur de la connexion."""
    feats = await _features(db, factory, conn_id)
    if not any(f["status"] == "missing" for f in feats):
        return []
    user = _get_or_404(db, conn_id).user
    try:
        roles = {r["roleid"] for r in shape_roles(await _px_get(db, factory, conn_id, "/access/roles"))}
    except HTTPException:
        roles = None
    return build_fixes(feats, user, roles)
