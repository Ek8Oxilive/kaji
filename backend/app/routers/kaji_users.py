"""Utilisateurs de Kaji et leurs rôles (lot #409) : lister, créer, changer de rôle ou de mot de passe, supprimer. **Administrateurs seulement** (`app/roles.py`, vérifié à chaque requête).

Garde-fous : on ne se supprime pas et on ne change pas son propre rôle (pas de verrouillage par accident) ; il reste toujours au moins un administrateur ;
suppression = `confirm=true` + nom retapé ; réinitialiser un mot de passe ou supprimer un compte révoque ses sessions (et sa session administrateur Proxmox).
Aucun mot de passe n'est jamais renvoyé ni journalisé.
"""
import re

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field, StrictBool
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import audit, roles
from ..adminsession import sessions as admin_sessions
from ..db import get_db
from ..models import AdminUser, UserSession
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


def _out(u: AdminUser) -> dict:
    return {"id": u.id, "username": u.username, "role": roles.normalize(u.role), "created_at": u.created_at.isoformat() if u.created_at else None}


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
    return [_out(u) for u in db.scalars(select(AdminUser).order_by(AdminUser.username))]


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
    if body.password is not None:
        u.password_hash = hash_password(body.password)
        _revoke(db, u)                                                       # un mot de passe réinitialisé déconnecte le compte partout
        changes.append("mot de passe réinitialisé, sessions révoquées")
    db.commit()
    _log(db, actor, "kaji-user-update", u.username, "started", ", ".join(changes) or "inchangé")
    return _out(u)


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
    db.delete(u)
    db.commit()
    _log(db, actor, "kaji-user-delete", username, "started", "compte et sessions supprimés")
    return {"deleted": username}
