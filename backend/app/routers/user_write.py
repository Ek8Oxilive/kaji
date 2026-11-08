"""Écrire des utilisateurs (realm pve), des groupes et des appartenances, avec l'identité de la session administrateur."""
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from .. import audit
from ..accessspec import shape_acl, shape_groups, shape_roles, shape_users
from ..adminsession import AdminSession
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..userwrite import (PVE_USER, GroupCreate, Membership, UserCreate, UserUpdate, dangerous_group_reason, group_usage, protected_reason,
                         update_params, user_params)
from ..aclwrite import GROUP
from .admin_session import admin_call, require_admin
from .cluster import Factory
from .connections import _get_or_404

router = APIRouter(prefix="/api/connections/{conn_id}/access", tags=["access-write"])
UID = Path(pattern=PVE_USER.pattern)
GID = Path(pattern=f"^{GROUP.pattern}$")


class Ctx:
    def __init__(self, db, user, conn_id, action, target):
        self.db, self.user, self.conn_id, self.action, self.target = db, user, conn_id, action, target

    def log(self, st, detail=None):
        audit.record(self.db, username=self.user.username, connection_id=self.conn_id, action=self.action, target=self.target, status=st, detail=detail)

    def refuse(self, msg, code):
        self.log("error", msg)
        raise HTTPException(code, msg)

    def confirmed(self, confirm: bool, typed: str | None, expected: str):
        if not confirm:
            self.refuse("Écriture de droits : renvoie la requête avec confirm=true et l'identifiant retapé", 400)
        if typed != expected:
            self.refuse("L'identifiant retapé ne correspond pas : écriture refusée", 400)


async def _users(db, factory, conn_id, s):
    return shape_users(await admin_call(db, factory, conn_id, s, "get", "/access/users"))


async def _groups(db, factory, conn_id, s):
    return shape_groups(await admin_call(db, factory, conn_id, s, "get", "/access/groups"))


async def _acl(db, factory, conn_id, s):
    return shape_acl(await admin_call(db, factory, conn_id, s, "get", "/access/acl"))


async def _user_groups(db, factory, conn_id, s, userid) -> list[str]:
    raw = await admin_call(db, factory, conn_id, s, "get", f"/access/users/{userid}")
    g = raw.get("groups") if isinstance(raw, dict) else None
    return sorted(x for x in (g if isinstance(g, list) else []) if isinstance(x, str))


def _prot(db, conn_id, userid, s):
    return protected_reason(userid, _get_or_404(db, conn_id).user, s.user)


async def _put(c: Ctx, db, factory, conn_id, s, method, path, **params):
    try:
        return await admin_call(db, factory, conn_id, s, method, path, **params)
    except HTTPException as e:
        c.log("error", str(e.detail))
        raise


# ---------------------------------------------------------------- utilisateurs
@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                      adm: tuple[AdminUser, AdminSession] = Depends(require_admin)):
    """Crée un utilisateur du realm pve. Sans mot de passe, il ne peut se connecter que par token. Ne lui donne aucun droit."""
    user, s = adm
    c = Ctx(db, user, conn_id, "user-create", body.userid)
    c.confirmed(body.confirm, body.type_name, body.userid)
    if reason := _prot(db, conn_id, body.userid, s):
        c.refuse(reason, 403)
    if any(u["userid"] == body.userid for u in await _users(db, factory, conn_id, s)):
        c.refuse("Cet utilisateur existe déjà", status.HTTP_409_CONFLICT)
    await _put(c, db, factory, conn_id, s, "post", "/access/users", **user_params(body))
    if not any(u["userid"] == body.userid for u in await _users(db, factory, conn_id, s)):
        c.refuse("Proxmox n'a pas créé l'utilisateur", status.HTTP_502_BAD_GATEWAY)
    c.log("started", f"créé (realm pve, {'avec' if body.password else 'sans'} mot de passe{'' if body.password is None else ' défini'}, "
                     f"{'activé' if body.enable else 'désactivé'})")
    return {"created": body.userid}


@router.put("/users/{userid}")
async def update_user(body: UserUpdate, conn_id: int, userid: str = UID, db: Session = Depends(get_db),
                      factory: Factory = Depends(get_client_factory), adm: tuple[AdminUser, AdminSession] = Depends(require_admin)):
    """Active, désactive ou modifie le commentaire et l'expiration d'un utilisateur pve."""
    user, s = adm
    c = Ctx(db, user, conn_id, "user-update", userid)
    c.confirmed(body.confirm, body.type_name, userid)
    params = update_params(body)
    if not params:
        c.refuse("Aucune modification demandée", 422)
    if reason := _prot(db, conn_id, userid, s):
        c.refuse(reason, 403)
    if not any(u["userid"] == userid for u in await _users(db, factory, conn_id, s)):
        c.refuse("Utilisateur inconnu", status.HTTP_404_NOT_FOUND)
    await _put(c, db, factory, conn_id, s, "put", f"/access/users/{userid}", **params)
    if body.enable is not None:
        now = next((u for u in await _users(db, factory, conn_id, s) if u["userid"] == userid), None)
        if now is None or now["enabled"] != body.enable:
            c.refuse("Proxmox n'a pas appliqué la modification", status.HTTP_502_BAD_GATEWAY)
    c.log("started", ", ".join(f"{k}={'défini' if k == 'password' else v}" for k, v in params.items()))
    return {"updated": userid}


@router.get("/users/{userid}/impact")
async def user_impact(conn_id: int, userid: str = UID, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                      adm: tuple[AdminUser, AdminSession] = Depends(require_admin)):
    """Ce que toucherait cet utilisateur : groupes, entrées d'ACL, tokens. Lecture seule (avant une suppression)."""
    _, s = adm
    raw = await admin_call(db, factory, conn_id, s, "get", f"/access/users/{userid}")
    acl = await _acl(db, factory, conn_id, s)
    tokens = raw.get("tokens") if isinstance(raw, dict) and isinstance(raw.get("tokens"), dict) else {}
    return {"userid": userid, "protected": _prot(db, conn_id, userid, s) is not None, "groups": await _user_groups(db, factory, conn_id, s, userid),
            "acl_entries": sum(1 for a in acl if a["ugid"] == userid or a["ugid"].startswith(userid + "!")), "tokens": sorted(t for t in tokens if isinstance(t, str))[:50]}


@router.delete("/users/{userid}")
async def delete_user(conn_id: int, userid: str = UID, confirm: bool = Query(default=False), name: str = Query(default="", max_length=80),
                      db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), adm: tuple[AdminUser, AdminSession] = Depends(require_admin)):
    """Supprime un utilisateur pve (et ses tokens). Exige confirm=true et son identifiant retapé."""
    user, s = adm
    c = Ctx(db, user, conn_id, "user-delete", userid)
    c.confirmed(confirm, name, userid)
    if reason := _prot(db, conn_id, userid, s):
        c.refuse(reason, 403)
    if not any(u["userid"] == userid for u in await _users(db, factory, conn_id, s)):
        c.refuse("Utilisateur inconnu", status.HTTP_404_NOT_FOUND)
    await _put(c, db, factory, conn_id, s, "delete", f"/access/users/{userid}")
    if any(u["userid"] == userid for u in await _users(db, factory, conn_id, s)):
        c.refuse("Proxmox n'a pas supprimé l'utilisateur", status.HTTP_502_BAD_GATEWAY)
    c.log("started", "supprimé")
    return {"deleted": userid}


@router.put("/users/{userid}/groups")
async def membership(body: Membership, conn_id: int, userid: str = UID, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                     adm: tuple[AdminUser, AdminSession] = Depends(require_admin)):
    """Ajoute ou retire l'utilisateur d'un groupe (un seul à la fois). Ajouter à un groupe qui porte un droit d'administration est refusé."""
    user, s = adm
    c = Ctx(db, user, conn_id, "group-member-add" if body.action == "add" else "group-member-remove", f"{userid} / {body.group}")
    c.confirmed(body.confirm, body.type_name, userid)
    if reason := _prot(db, conn_id, userid, s):
        c.refuse(reason, 403)
    users, groups = await _users(db, factory, conn_id, s), await _groups(db, factory, conn_id, s)
    if not any(u["userid"] == userid for u in users):
        c.refuse("Utilisateur inconnu", status.HTTP_404_NOT_FOUND)
    if not any(g["groupid"] == body.group for g in groups):
        c.refuse("Groupe inconnu", status.HTTP_404_NOT_FOUND)
    current = await _user_groups(db, factory, conn_id, s, userid)
    if body.action == "add":
        if body.group in current:
            c.refuse("Déjà membre de ce groupe", status.HTTP_409_CONFLICT)
        reason = dangerous_group_reason(body.group, await _acl(db, factory, conn_id, s), shape_roles(await admin_call(db, factory, conn_id, s, "get", "/access/roles")))
        if reason:
            c.refuse(reason, 403)
        params = {"groups": body.group, "append": 1}
    else:
        if body.group not in current:
            c.refuse("Pas membre de ce groupe", status.HTTP_404_NOT_FOUND)
        params = {"groups": ",".join(g for g in current if g != body.group)}
    await _put(c, db, factory, conn_id, s, "put", f"/access/users/{userid}", **params)
    if (body.group in await _user_groups(db, factory, conn_id, s, userid)) != (body.action == "add"):
        c.refuse("Proxmox n'a pas appliqué la modification", status.HTTP_502_BAD_GATEWAY)
    c.log("started", f"{body.action} {body.group}")
    return {"user": userid, "group": body.group, "action": body.action}


# ---------------------------------------------------------------- groupes
@router.post("/groups", status_code=status.HTTP_201_CREATED)
async def create_group(body: GroupCreate, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                       adm: tuple[AdminUser, AdminSession] = Depends(require_admin)):
    user, s = adm
    c = Ctx(db, user, conn_id, "group-create", body.groupid)
    c.confirmed(body.confirm, body.type_name, body.groupid)
    if any(g["groupid"] == body.groupid for g in await _groups(db, factory, conn_id, s)):
        c.refuse("Ce groupe existe déjà", status.HTTP_409_CONFLICT)
    params: dict = {"groupid": body.groupid}
    if body.comment:
        params["comment"] = body.comment
    await _put(c, db, factory, conn_id, s, "post", "/access/groups", **params)
    if not any(g["groupid"] == body.groupid for g in await _groups(db, factory, conn_id, s)):
        c.refuse("Proxmox n'a pas créé le groupe", status.HTTP_502_BAD_GATEWAY)
    c.log("started", "créé (sans droit)")
    return {"created": body.groupid}


@router.delete("/groups/{groupid}")
async def delete_group(conn_id: int, groupid: str = GID, confirm: bool = Query(default=False), name: str = Query(default="", max_length=80),
                       db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), adm: tuple[AdminUser, AdminSession] = Depends(require_admin)):
    """Supprime un groupe **vide** et sans ACL (on ne perd pas de droits en silence)."""
    user, s = adm
    c = Ctx(db, user, conn_id, "group-delete", groupid)
    c.confirmed(confirm, name, groupid)
    groups = await _groups(db, factory, conn_id, s)
    if not any(g["groupid"] == groupid for g in groups):
        c.refuse("Groupe inconnu", status.HTTP_404_NOT_FOUND)
    members, entries = group_usage(groupid, groups, await _acl(db, factory, conn_id, s))
    if members or entries:
        c.refuse(f"Groupe encore utilisé ({len(members)} membre(s), {entries} entrée(s) d'ACL) : vide-le d'abord", status.HTTP_409_CONFLICT)
    await _put(c, db, factory, conn_id, s, "delete", f"/access/groups/{groupid}")
    if any(g["groupid"] == groupid for g in await _groups(db, factory, conn_id, s)):
        c.refuse("Proxmox n'a pas supprimé le groupe", status.HTTP_502_BAD_GATEWAY)
    c.log("started", "supprimé")
    return {"deleted": groupid}
