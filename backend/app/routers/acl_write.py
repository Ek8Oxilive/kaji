"""Écrire une entrée d'ACL (ajouter ou retirer), avec l'identité de la session administrateur. Une entrée à la fois ; aperçu puis application."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import audit
from ..accessspec import granted, shape_acl, shape_groups, shape_roles
from ..aclwrite import AclApply, AclChange, entries_for, find_entry, proxmox_params, refusal, role_privs
from ..adminsession import AdminSession
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from .admin_session import admin_call, require_admin
from .cluster import Factory
from .connections import _get_or_404

router = APIRouter(prefix="/api/connections/{conn_id}/access/acl", tags=["access-write"])


class Ctx:
    def __init__(self, db, user, conn_id, action, target):
        self.db, self.user, self.conn_id, self.action, self.target = db, user, conn_id, action, target

    def log(self, st, detail=None):
        audit.record(self.db, username=self.user.username, connection_id=self.conn_id, action=self.action, target=self.target,
                     status=st, detail=detail)

    def refuse(self, msg, code):
        self.log("error", msg)
        raise HTTPException(code, msg)


async def _state(db, factory, conn_id, s: AdminSession):
    """Rôles, groupes et ACL relus chez Proxmox avec l'identité de la session administrateur (jamais une valeur du navigateur)."""
    roles = shape_roles(await admin_call(db, factory, conn_id, s, "get", "/access/roles"))
    groups = shape_groups(await admin_call(db, factory, conn_id, s, "get", "/access/groups"))
    acl = shape_acl(await admin_call(db, factory, conn_id, s, "get", "/access/acl"))
    return roles, groups, acl


def _refusal(db, conn_id, ch, roles, groups, s):
    conn = _get_or_404(db, conn_id)
    return refusal(ch, roles, groups, conn.user, s.user)


def _detail(ch: AclChange) -> str:
    return f"{ch.action} {ch.role} pour {ch.ugid} sur {ch.path}" + (f" (propagate={int(ch.propagate)})" if ch.action == "add" else "")


@router.post("/preview")
async def preview(body: AclChange, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                  adm: tuple[AdminUser, AdminSession] = Depends(require_admin)):
    """Ce que ferait l'écriture : entrées existantes, privilèges du rôle, droits effectifs avant et estimation après. **N'écrit rien.**"""
    _, s = adm
    roles, groups, acl = await _state(db, factory, conn_id, s)
    reason = _refusal(db, conn_id, body, roles, groups, s)
    privs = role_privs(roles, body.role)
    exists = find_entry(acl, body) is not None
    before: set[str] | None = None
    if reason is None and body.kind in ("user", "token"):
        raw = await admin_call(db, factory, conn_id, s, "get", "/access/permissions", userid=body.ugid, path=body.path)
        before = granted(raw.get(body.path)) if isinstance(raw, dict) else None
    after = sorted(before | privs) if before is not None and privs is not None and body.action == "add" else None
    return {"allowed": reason is None, "reason": reason, "entry_exists": exists,
            "would_change": reason is None and (exists if body.action == "remove" else not exists),
            "existing_entries": entries_for(acl, body), "role_privs": sorted(privs) if privs is not None else None,
            "effective_before": sorted(before) if before is not None else None, "estimate_after": after,
            "note": "Estimation : Proxmox ne fait pas de simulation ; l'héritage depuis les chemins parents compte déjà dans « avant »."}


@router.put("")
async def apply(body: AclApply, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                adm: tuple[AdminUser, AdminSession] = Depends(require_admin)):
    """Ajoute ou retire **une** entrée d'ACL. Exige confirm=true et l'identifiant retapé ; tous les interdits sont revérifiés ici."""
    user, s = adm
    c = Ctx(db, user, conn_id, "acl-add" if body.action == "add" else "acl-remove", f"{body.path} {body.ugid}")
    if not body.confirm:
        c.refuse("Écriture de droits : renvoie la requête avec {\"confirm\": true} et l'identifiant retapé (type_name)", 400)
    if body.type_name != body.ugid:
        c.refuse("L'identifiant retapé ne correspond pas : écriture refusée", 400)
    roles, groups, acl = await _state(db, factory, conn_id, s)
    reason = _refusal(db, conn_id, body, roles, groups, s)
    if reason:
        c.refuse(reason, status.HTTP_403_FORBIDDEN)
    exists = find_entry(acl, body) is not None
    if body.action == "add" and exists:
        c.refuse("Cette entrée existe déjà", status.HTTP_409_CONFLICT)
    if body.action == "remove" and not exists:
        c.refuse("Cette entrée n'existe pas", status.HTTP_404_NOT_FOUND)
    try:
        await admin_call(db, factory, conn_id, s, "put", "/access/acl", **proxmox_params(body))
    except HTTPException as e:
        c.log("error", str(e.detail))
        raise
    after = shape_acl(await admin_call(db, factory, conn_id, s, "get", "/access/acl"))
    done = find_entry(after, body) is not None
    if done != (body.action == "add"):                 # Proxmox a répondu mais l'état ne correspond pas : on ne prétend pas avoir réussi
        c.refuse("Proxmox n'a pas appliqué la modification (vérifie les droits du token d'administration)", status.HTTP_502_BAD_GATEWAY)
    c.log("started", _detail(body))
    return {"applied": True, "action": body.action, "path": body.path, "ugid": body.ugid, "role": body.role}
