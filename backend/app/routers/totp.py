"""Double authentification (TOTP) pour se connecter à Kaji (lot #444, jalon J2) : seconde étape de la connexion, activation, codes de secours, désactivation.

- La connexion se fait en DEUX étapes : `POST /api/auth/login` (mot de passe) renvoie un défi de 5 minutes si le compte a le TOTP, puis `POST /api/auth/login/totp` (défi + code) ouvre la session.
- Un code déjà accepté ne l'est jamais deux fois ; 5 échecs par 5 minutes bloquent l'adresse ET le compte ; un code de secours ne sert qu'une fois.
- Le secret n'est montré qu'à l'activation ; les codes de secours aussi (une seule fois). Rien de tout cela n'est jamais journalisé.
- Tous les rôles peuvent protéger LEUR compte (`/api/auth/` est en libre-service) ; seul un administrateur retire le TOTP d'un AUTRE compte (`DELETE /api/kaji-users/{id}/totp`).
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit, totp, totpstore
from ..config import get_settings
from ..db import get_db
from ..models import AdminUser, UserTotp
from ..security import challenge_matches, create_totp_challenge, decode_totp_challenge, throttle, verify_password
from .auth import _ip, _start_session, current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginTotp(BaseModel):
    challenge: str = Field(min_length=10, max_length=2000)
    code: str = Field(min_length=6, max_length=40)


class PasswordBody(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class CodeBody(BaseModel):
    code: str = Field(min_length=6, max_length=40)


class PasswordCode(PasswordBody):
    code: str = Field(min_length=6, max_length=40)


def _key() -> str:
    return get_settings().kaji_secret_key


def _log(db: Session, username: str, action: str, st: str, detail: str | None = None) -> None:
    audit.record(db, username=username, connection_id=None, action=action, target="admin", status=st, detail=detail)


def _too_many() -> HTTPException:
    return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Trop de tentatives, réessaie plus tard")


def begin_totp_login(user: AdminUser) -> dict:
    """Réponse de la première étape quand le compte a le TOTP : un défi, pas une session."""
    return {"totp_required": True, "challenge": create_totp_challenge(_key(), user.id, user.password_hash)}


@router.post("/login/totp")
def login_totp(body: LoginTotp, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = _ip(request)
    if throttle.blocked(ip):
        raise _too_many()
    decoded = decode_totp_challenge(_key(), body.challenge)
    user = db.get(AdminUser, decoded[0]) if decoded else None
    if decoded is None or user is None or not challenge_matches(user.password_hash, decoded[1]):
        throttle.fail(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Connexion expirée : reconnecte-toi avec ton mot de passe")
    account = f"totp:{user.id}"
    if throttle.blocked(account):
        raise _too_many()
    kind = totpstore.check(db, _key(), user.id, body.code)
    if kind is None:
        throttle.fail(ip)
        throttle.fail(account)
        _log(db, user.username, "login-totp", "error", "code invalide")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Code invalide")
    throttle.reset(ip)
    throttle.reset(account)
    if kind == "recovery":
        _log(db, user.username, "totp-recovery-used", "started", f"{totpstore.remaining_recovery(db, user.id)} code(s) de secours restant(s)")
    _start_session(db, response, user.id)
    return {"username": user.username}


@router.get("/totp")
def totp_status(user: AdminUser = Depends(current_user), db: Session = Depends(get_db)):
    row = db.get(UserTotp, user.id)
    enabled = row is not None and bool(row.confirmed)
    return {"enabled": enabled, "pending": row is not None and not row.confirmed,
            "recovery_remaining": totpstore.remaining_recovery(db, user.id) if enabled else 0}


def _check_password(db: Session, request: Request, user: AdminUser, password: str, action: str) -> None:
    key = f"pw:{_ip(request)}"
    if throttle.blocked(key):
        raise _too_many()
    if not verify_password(password, user.password_hash):
        throttle.fail(key)
        _log(db, user.username, action, "error", "mot de passe incorrect")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Mot de passe incorrect")
    throttle.reset(key)


def _check_code(db: Session, user: AdminUser, code: str, action: str, *, allow_recovery: bool) -> str:
    account = f"totp:{user.id}"
    if throttle.blocked(account):
        raise _too_many()
    kind = totpstore.check(db, _key(), user.id, code, allow_recovery=allow_recovery)
    if kind is None:
        throttle.fail(account)
        _log(db, user.username, action, "error", "code invalide")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Code invalide")
    throttle.reset(account)
    return kind


@router.post("/totp/setup")
def totp_setup(body: PasswordBody, request: Request, user: AdminUser = Depends(current_user), db: Session = Depends(get_db)):
    """Démarre l'activation : génère un secret (NON exigé à la connexion tant qu'un premier code n'a pas été confirmé). Demande le mot de passe : une session volée ne suffit pas."""
    _check_password(db, request, user, body.password, "totp-setup")
    if totpstore.is_enabled(db, user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "La double authentification est déjà activée")
    secret = totpstore.start_enrollment(db, _key(), user.id)
    _log(db, user.username, "totp-setup", "started", "secret généré, en attente de confirmation")
    return {"secret": secret, "uri": totp.otpauth_uri(secret, user.username)}


@router.post("/totp/confirm")
def totp_confirm(body: CodeBody, user: AdminUser = Depends(current_user), db: Session = Depends(get_db)):
    """Premier code valide : active le TOTP et affiche les codes de secours, UNE SEULE FOIS."""
    account = f"totp:{user.id}"
    if throttle.blocked(account):
        raise _too_many()
    row = db.get(UserTotp, user.id)
    if row is None or row.confirmed:
        raise HTTPException(status.HTTP_409_CONFLICT, "Aucune activation en cours : démarre-la d'abord")
    codes = totpstore.confirm_enrollment(db, _key(), user.id, body.code)
    if codes is None:
        throttle.fail(account)
        _log(db, user.username, "totp-confirm", "error", "code invalide")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Code invalide")
    throttle.reset(account)
    _log(db, user.username, "totp-enabled", "started", f"{len(codes)} codes de secours émis")
    return {"enabled": True, "recovery_codes": codes}


@router.post("/totp/recovery")
def totp_new_recovery_codes(body: PasswordCode, request: Request, user: AdminUser = Depends(current_user), db: Session = Depends(get_db)):
    """Nouveaux codes de secours (les anciens cessent de valoir). Exige le mot de passe ET un code de l'application (pas un code de secours)."""
    if not totpstore.is_enabled(db, user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "La double authentification n'est pas activée")
    _check_password(db, request, user, body.password, "totp-recovery")
    _check_code(db, user, body.code, "totp-recovery", allow_recovery=False)
    codes = totpstore.regenerate_recovery(db, _key(), user.id)
    _log(db, user.username, "totp-recovery", "started", f"{len(codes)} nouveaux codes de secours")
    return {"recovery_codes": codes}


@router.post("/totp/disable")
def totp_disable(body: PasswordCode, request: Request, user: AdminUser = Depends(current_user), db: Session = Depends(get_db)):
    """Désactive le TOTP de SON compte : mot de passe ET un code (de l'application ou de secours)."""
    if not totpstore.is_enabled(db, user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "La double authentification n'est pas activée")
    _check_password(db, request, user, body.password, "totp-disable")
    _check_code(db, user, body.code, "totp-disable", allow_recovery=True)
    totpstore.remove(db, user.id)
    _log(db, user.username, "totp-disabled", "started", "par le titulaire")
    return {"enabled": False}
