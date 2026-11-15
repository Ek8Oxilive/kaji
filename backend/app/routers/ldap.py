"""Connexion par annuaire LDAP / Active Directory (lot #443, jalon J2) : `POST /api/auth/ldap/login` et l'état pour l'écran de connexion. Règles : `app/ldaplogin.py`, `docs/api/ldap.md`.

- Désactivée (404) tant que `KAJI_LDAP_URL` est vide ; le mot de passe local reste le repli.
- Le compte de Kaji reste la source du rôle et du périmètre ; si le compte a le TOTP de Kaji, le code est encore demandé (l'annuaire ne dit rien de son second facteur).
- Refus : TOUJOURS le même message (401) et un MOTIF COURT dans l'audit ; ni le mot de passe, ni le détail de l'annuaire.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit, ldaplogin, totpstore
from ..config import get_settings
from ..db import get_db
from ..security import throttle
from .auth import _ip, _start_session

router = APIRouter(prefix="/api/auth/ldap", tags=["auth"])


class LdapCredentials(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=256)


@router.get("/status")
def ldap_status():
    s = get_settings()
    on = ldaplogin.enabled(s)
    return {"enabled": on, "label": s.kaji_ldap_label[:40] if on else None}


@router.post("/login")
def ldap_login(body: LdapCredentials, request: Request, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    if not ldaplogin.enabled(s):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Annuaire non configuré")
    key = f"ldap:{_ip(request)}"
    if throttle.blocked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Trop de tentatives, réessaie plus tard")

    def refuse(reason: str, who: str = "ldap"):
        throttle.fail(key)
        audit.record(db, username=who[:64], connection_id=None, action="login-ldap", target="ldap", status="error", detail=reason[:150])
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Identifiants invalides")

    try:
        name, dn = ldaplogin.authenticate(body.username, body.password, s)
    except ldaplogin.LdapError as e:
        refuse(str(e))
    user = ldaplogin.resolve_user(db, name, dn, s)
    if user is None:
        refuse("aucun compte de Kaji pour cette personne", who=name)
    if totpstore.is_enabled(db, user.id):
        from .totp import begin_totp_login
        return begin_totp_login(user)
    throttle.reset(key)
    _start_session(db, response, user.id)
    audit.record(db, username=user.username, connection_id=None, action="login-ldap", target="ldap", status="started", detail="connexion par l'annuaire")
    return {"username": user.username}
