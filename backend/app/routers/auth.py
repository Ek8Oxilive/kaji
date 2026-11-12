import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import audit
from ..adminsession import sessions as admin_sessions
from ..config import get_settings
from ..db import get_db
from ..models import AdminUser, UserSession
from ..security import (
    client_ip,
    create_session_token,
    decode_session,
    hash_password,
    throttle,
    verify_password,
)

COOKIE = "kaji_session"
router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class SetupRequest(Credentials):
    password: str = Field(min_length=12, max_length=256)
    setup_token: str | None = Field(default=None, max_length=256, description="Jeton de première configuration (`KAJI_SETUP_TOKEN`), s'il est défini")


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)      # SQLite renvoie des dates sans fuseau (UTC)


def _ip(request: Request) -> str:
    return client_ip(request, get_settings().kaji_trust_proxy)


def _start_session(db: Session, response: Response, user_id: int) -> None:
    """Ouvre une session : une ligne en base (révocable) et un jeton signé qui y renvoie."""
    s = get_settings()
    db.execute(delete(UserSession).where(UserSession.expires_at < _now()))      # ménage des sessions expirées
    jti = secrets.token_urlsafe(24)
    db.add(UserSession(id=jti, user_id=user_id, expires_at=_now() + timedelta(hours=s.kaji_session_hours)))
    db.commit()
    response.set_cookie(
        COOKIE,
        create_session_token(s.kaji_secret_key, user_id, s.kaji_session_hours, jti),
        max_age=s.kaji_session_hours * 3600,
        httponly=True,
        secure=s.kaji_cookie_secure,
        samesite="strict",
        path="/",
    )


def _session_of(request: Request, db: Session) -> tuple[AdminUser, UserSession] | None:
    """La session du cookie, seulement si elle existe encore en base, n'a pas expiré et correspond à l'utilisateur."""
    token = request.cookies.get(COOKIE)
    decoded = decode_session(get_settings().kaji_secret_key, token) if token else None
    if decoded is None:
        return None
    uid, jti = decoded
    sess = db.get(UserSession, jti)
    user = db.get(AdminUser, uid)
    if sess is None or user is None or sess.user_id != uid or _aware(sess.expires_at) < _now():
        return None
    return user, sess


def current_user(request: Request, db: Session = Depends(get_db)) -> AdminUser:
    found = _session_of(request, db)
    if found is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Non authentifié")
    return found[0]


def _has_admin(db: Session) -> bool:
    return db.scalar(select(func.count()).select_from(AdminUser)) > 0


@router.get("/status")
def auth_status(request: Request, db: Session = Depends(get_db)):
    setup_required = not _has_admin(db)
    return {"setup_required": setup_required, "authenticated": _session_of(request, db) is not None,
            "setup_token_required": setup_required and bool(get_settings().kaji_setup_token)}


@router.post("/setup", status_code=status.HTTP_201_CREATED)
def setup(body: SetupRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    if _has_admin(db):
        raise HTTPException(status.HTTP_409_CONFLICT, "Le compte admin existe déjà")
    expected = get_settings().kaji_setup_token
    if expected:
        key = f"setup:{_ip(request)}"
        if throttle.blocked(key):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Trop de tentatives, réessaie plus tard")
        if not secrets.compare_digest((body.setup_token or "").encode(), expected.encode()):          # temps constant : pas de devinette octet par octet
            throttle.fail(key)
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Jeton de première configuration manquant ou invalide")
        throttle.reset(key)
    user = AdminUser(username=body.username, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    _start_session(db, response, user.id)
    return {"username": user.username}


@router.post("/login")
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = _ip(request)
    if throttle.blocked(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Trop de tentatives, réessaie plus tard")
    user = db.scalar(select(AdminUser).where(AdminUser.username == body.username))
    if not verify_password(body.password, user.password_hash if user else None) or user is None:
        throttle.fail(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Identifiants invalides")
    throttle.reset(ip)
    _start_session(db, response, user.id)
    return {"username": user.username}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """Révoque la session courante côté serveur : un jeton copié ne sert plus à rien après la déconnexion."""
    found = _session_of(request, db)
    if found:
        admin_sessions.close(found[1].id)               # la session administrateur disparaît avec la session de connexion
        db.delete(found[1])
        db.commit()
    response.delete_cookie(COOKIE, path="/")


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(response: Response, user: AdminUser = Depends(current_user), db: Session = Depends(get_db)):
    """Révoque toutes les sessions du compte, y compris la courante."""
    admin_sessions.close_owner(user.id)
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    db.commit()
    audit.record(db, username=user.username, connection_id=None, action="logout-all", target="admin", status="started")
    response.delete_cookie(COOKIE, path="/")


@router.post("/password")
def change_password(body: PasswordChange, request: Request, response: Response,
                    user: AdminUser = Depends(current_user), db: Session = Depends(get_db)):
    """Change le mot de passe. Toutes les autres sessions sont révoquées ; la session courante est renouvelée."""
    key = f"pw:{_ip(request)}"
    if throttle.blocked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Trop de tentatives, réessaie plus tard")
    if not verify_password(body.current_password, user.password_hash):
        throttle.fail(key)
        audit.record(db, username=user.username, connection_id=None, action="password-change", target="admin",
                     status="error", detail="mot de passe actuel incorrect")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Mot de passe actuel incorrect")
    if body.new_password == body.current_password:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Le nouveau mot de passe doit être différent de l'actuel")
    throttle.reset(key)
    user.password_hash = hash_password(body.new_password)
    admin_sessions.close_owner(user.id)
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    db.commit()
    _start_session(db, response, user.id)
    audit.record(db, username=user.username, connection_id=None, action="password-change", target="admin",
                 status="started", detail="autres sessions révoquées")
    return {"changed": True}


@router.get("/me")
def me(user: AdminUser = Depends(current_user)):
    return {"username": user.username}
