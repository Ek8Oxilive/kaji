"""Utilisateurs de Kaji et leurs rôles (lot #409) : lister, créer, changer de rôle ou de mot de passe, supprimer. **Administrateurs seulement** (`app/roles.py`, vérifié à chaque requête).

Garde-fous : on ne se supprime pas et on ne change pas son propre rôle (pas de verrouillage par accident) ; il reste toujours au moins un administrateur ;
suppression = `confirm=true` + nom retapé ; réinitialiser un mot de passe ou supprimer un compte révoque ses sessions (et sa session administrateur Proxmox).
Aucun mot de passe n'est jamais renvoyé ni journalisé.
"""
import re

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field, StrictBool, StrictInt, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import audit, roles, scope, totpstore
from ..adminsession import sessions as admin_sessions
from ..db import get_db
from ..models import AdminUser, Connection, UserScope, UserSession, UserToken
from ..security import hash_password
from .auth import current_user

router = APIRouter(prefix="/api/kaji-users", tags=["kaji-users"])
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
Role = str


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
    password: str = Field(min_length=12, max_length=256)
    role: str = Field(pattern=r"^(admin|operator|viewer)$")


class UserUpdate(BaseModel):
    role: str | None = Field(default=None, pattern=r"^(admin|operator|viewer)$")
    password: str | None = Field(default=None, min_length=12, max_length=256)


def _out(u: AdminUser, totp_on: bool = False, scoped: bool = False) -> dict:
    return {"id": u.id, "username": u.username, "role": roles.normalize(u.role), "created_at": u.created_at.isoformat() if u.created_at else None, "totp": totp_on, "scoped": scoped}


def _admins(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(AdminUser).where(AdminUser.role == "admin")) or 0


def _log(db, actor: AdminUser, action: str, target: str, st: str, detail: str | None = None):
    audit.record(db, username=actor.username, connection_id=None, action=action, target=target, status=st, detail=detail)


def _refuse(db, actor, action, target, msg, code):
    _log(db, actor, action, target, "error", msg)
    raise HTTPException(code, msg)


def _revoke(db: Session, user: AdminUser) -> None:
    admin_sessions.close_owner(user.id)
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))


@router.get("")
def list_users(db: Session = Depends(get_db), _a: AdminUser = Depends(current_user)):
    on = totpstore.enabled_ids(db)
    limited = set(db.scalars(select(UserScope.user_id)).all())
    return [_out(u, u.id in on, u.id in limited) for u in db.scalars(select(AdminUser).order_by(AdminUser.username))]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, db: Session = Depends(get_db), actor: AdminUser = Depends(current_user)):
    if db.scalar(select(AdminUser).where(func.lower(AdminUser.username) == body.username.lower())):
        _refuse(db, actor, "kaji-user-create", body.username, "Ce nom d'utilisateur existe déjà", status.HTTP_409_CONFLICT)
    u = AdminUser(username=body.username, password_hash=hash_password(body.password), role=body.role)
    db.add(u)
    db.commit()
    _log(db, actor, "kaji-user-create", u.username, "started", f"rôle {u.role}")
    return _out(u)


@router.put("/{user_id}")
def update_user(body: UserUpdate, user_id: int = Path(ge=1), db: Session = Depends(get_db), actor: AdminUser = Depends(current_user)):
    u = db.get(AdminUser, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Utilisateur inconnu")
    if body.role is None and body.password is None:
        _refuse(db, actor, "kaji-user-update", u.username, "Aucune modification demandée", status.HTTP_422_UNPROCESSABLE_CONTENT)
    if body.role is not None and u.id == actor.id and body.role != roles.normalize(actor.role):
        _refuse(db, actor, "kaji-user-update", u.username, "Tu ne peux pas changer ton propre rôle", status.HTTP_409_CONFLICT)
    if body.role is not None and roles.normalize(u.role) == "admin" and body.role != "admin" and _admins(db) <= 1:
        _refuse(db, actor, "kaji-user-update", u.username, "Il doit rester au moins un administrateur", status.HTTP_409_CONFLICT)
    changes = []
    if body.role is not None and body.role != u.role:
        u.role = body.role
        changes.append(f"rôle {body.role}")
        if body.role == "admin" and scope.scope_of(db, u.id) is not None:
            db.execute(delete(UserScope).where(UserScope.user_id == u.id))
            changes.append("périmètre retiré (un administrateur n'en a pas)")
    if body.password is not None:
        u.password_hash = hash_password(body.password)
        _revoke(db, u)                                                       # un mot de passe réinitialisé déconnecte le compte partout
        changes.append("mot de passe réinitialisé, sessions révoquées")
    db.commit()
    _log(db, actor, "kaji-user-update", u.username, "started", ", ".join(changes) or "inchangé")
    return _out(u, totpstore.is_enabled(db, u.id), scope.scope_of(db, u.id) is not None)


@router.delete("/{user_id}")
def delete_user(user_id: int = Path(ge=1), confirm: StrictBool = Query(default=False), name: str = Query(default="", max_length=80),
                db: Session = Depends(get_db), actor: AdminUser = Depends(current_user)):
    u = db.get(AdminUser, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Utilisateur inconnu")
    if u.id == actor.id:
        _refuse(db, actor, "kaji-user-delete", u.username, "Tu ne peux pas supprimer ton propre compte", status.HTTP_409_CONFLICT)
    if roles.normalize(u.role) == "admin" and _admins(db) <= 1:
        _refuse(db, actor, "kaji-user-delete", u.username, "Il doit rester au moins un administrateur", status.HTTP_409_CONFLICT)
    if not confirm or name != u.username:
        _refuse(db, actor, "kaji-user-delete", u.username, "Suppression : renvoie la requête avec confirm=true et le nom d'utilisateur retapé", status.HTTP_400_BAD_REQUEST)
    username = u.username
    _revoke(db, u)
    db.execute(delete(UserToken).where(UserToken.user_id == u.id))             # ses jetons Proxmox personnels disparaissent avec lui
    totpstore.remove(db, u.id)                                                  # et sa double authentification (secret chiffré, codes de secours)
    db.execute(delete(UserScope).where(UserScope.user_id == u.id))             # et son périmètre
    db.delete(u)
    db.commit()
    _log(db, actor, "kaji-user-delete", username, "started", "compte, sessions et jetons Proxmox personnels supprimés")
    return {"deleted": username}


@router.delete("/{user_id}/totp")
def remove_totp(user_id: int = Path(ge=1), confirm: StrictBool = Query(default=False), name: str = Query(default="", max_length=80),
                db: Session = Depends(get_db), actor: AdminUser = Depends(current_user)):
    """Retire la double authentification d'UN AUTRE compte (téléphone perdu, plus de codes de secours). Pas pour soi-même : une session volée ne doit pas pouvoir désactiver
    le second facteur de son propre compte (utiliser `POST /api/auth/totp/disable`, qui exige le mot de passe ET un code). `confirm=true` + nom retapé ; les sessions du compte sont révoquées."""
    u = db.get(AdminUser, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Utilisateur inconnu")
    if u.id == actor.id:
        _refuse(db, actor, "kaji-user-totp-remove", u.username, "Pour retirer ta propre double authentification, utilise la désactivation (mot de passe et code)", status.HTTP_409_CONFLICT)
    if not confirm or name != u.username:
        _refuse(db, actor, "kaji-user-totp-remove", u.username, "Retrait : renvoie la requête avec confirm=true et le nom d'utilisateur retapé", status.HTTP_400_BAD_REQUEST)
    if not totpstore.is_enabled(db, u.id):
        _refuse(db, actor, "kaji-user-totp-remove", u.username, "Ce compte n'a pas la double authentification", status.HTTP_409_CONFLICT)
    totpstore.remove(db, u.id)
    _revoke(db, u)
    db.commit()
    _log(db, actor, "kaji-user-totp-remove", u.username, "started", "double authentification retirée, sessions du compte révoquées")
    return {"removed": u.username}


# ---------------------------------------------------------------- périmètre d'un compte (lot #447)
MAX_MACHINES = 500
MAX_CONNECTIONS = 20


class ScopeEntry(BaseModel):
    conn_id: StrictInt = Field(ge=1, le=999_999_999)                      # entiers STRICTS : `true` ou "115" ne sont pas des identifiants
    vmids: list[StrictInt] = Field(min_length=1, max_length=MAX_MACHINES)

    @field_validator("vmids")
    @classmethod
    def _vmids(cls, v: list[int]):
        if any(not 1 <= x <= 999_999_999 for x in v):
            raise ValueError("identifiant de machine invalide")
        if len(set(v)) != len(v):
            raise ValueError("identifiant de machine en double")
        return v


class ScopeBody(BaseModel):
    entries: list[ScopeEntry] = Field(min_length=1, max_length=MAX_CONNECTIONS)


def _scope_out(db: Session, user_id: int) -> dict:
    limits = scope.scope_of(db, user_id)
    return {"restricted": limits is not None, "entries": [{"conn_id": c, "vmids": sorted(v)} for c, v in sorted((limits or {}).items())]}


@router.get("/{user_id}/scope")
def get_scope(user_id: int = Path(ge=1), db: Session = Depends(get_db), _a: AdminUser = Depends(current_user)):
    if db.get(AdminUser, user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Utilisateur inconnu")
    return _scope_out(db, user_id)


@router.put("/{user_id}/scope")
def set_scope(body: ScopeBody, user_id: int = Path(ge=1), db: Session = Depends(get_db), actor: AdminUser = Depends(current_user)):
    """Remplace le périmètre du compte : les machines (par connexion) qu'il voit et touche, et rien d'autre (`app/scope.py`). Jamais pour un administrateur. Prend effet tout de suite, sur les requêtes
    et les flux déjà ouverts. Une liste vide est refusée (422) : retirer la restriction est une action à part, avec confirmation (`DELETE`)."""
    u = db.get(AdminUser, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Utilisateur inconnu")
    if roles.normalize(u.role) == "admin":
        _refuse(db, actor, "kaji-user-scope", u.username, "Un administrateur n'a pas de périmètre : passe d'abord le compte en opérateur ou en lecture seule", status.HTTP_409_CONFLICT)
    conns = [e.conn_id for e in body.entries]
    if len(set(conns)) != len(conns):
        _refuse(db, actor, "kaji-user-scope", u.username, "Une connexion ne peut apparaître qu'une fois", status.HTTP_422_UNPROCESSABLE_CONTENT)
    known = set(db.scalars(select(Connection.id).where(Connection.id.in_(conns))).all())
    if known != set(conns):
        _refuse(db, actor, "kaji-user-scope", u.username, "Connexion inconnue", status.HTTP_422_UNPROCESSABLE_CONTENT)
    db.execute(delete(UserScope).where(UserScope.user_id == u.id))
    for e in body.entries:
        for vmid in e.vmids:
            db.add(UserScope(user_id=u.id, conn_id=e.conn_id, vmid=vmid))
    db.commit()
    total = sum(len(e.vmids) for e in body.entries)
    _log(db, actor, "kaji-user-scope", u.username, "started", f"périmètre : {total} machine(s) sur {len(conns)} connexion(s)")
    return _scope_out(db, u.id)


@router.delete("/{user_id}/scope")
def clear_scope(user_id: int = Path(ge=1), confirm: StrictBool = Query(default=False), name: str = Query(default="", max_length=80),
                db: Session = Depends(get_db), actor: AdminUser = Depends(current_user)):
    """Retire la restriction : le compte revient à la politique de son rôle sur TOUT le cluster. Élargit les droits : `confirm=true` + nom retapé."""
    u = db.get(AdminUser, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Utilisateur inconnu")
    if not confirm or name != u.username:
        _refuse(db, actor, "kaji-user-scope-clear", u.username, "Retrait du périmètre : renvoie la requête avec confirm=true et le nom d'utilisateur retapé", status.HTTP_400_BAD_REQUEST)
    if scope.scope_of(db, u.id) is None:
        _refuse(db, actor, "kaji-user-scope-clear", u.username, "Ce compte n'a pas de périmètre", status.HTTP_409_CONFLICT)
    db.execute(delete(UserScope).where(UserScope.user_id == u.id))
    db.commit()
    _log(db, actor, "kaji-user-scope-clear", u.username, "started", "restriction retirée : le compte revient à la politique de son rôle")
    return _scope_out(db, u.id)
