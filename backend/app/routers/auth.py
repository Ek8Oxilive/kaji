from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import AdminUser
from ..security import (
    create_session_token,
    decode_session_token,
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


def _set_cookie(response: Response, user_id: int) -> None:
    s = get_settings()
    response.set_cookie(
        COOKIE,
        create_session_token(s.kaji_secret_key, user_id, s.kaji_session_hours),
        max_age=s.kaji_session_hours * 3600,
        httponly=True,
        secure=s.kaji_cookie_secure,
        samesite="strict",
        path="/",
    )


def current_user(request: Request, db: Session = Depends(get_db)) -> AdminUser:
    token = request.cookies.get(COOKIE)
    user_id = decode_session_token(get_settings().kaji_secret_key, token) if token else None
    user = db.get(AdminUser, user_id) if user_id else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Non authentifié")
    return user


def _has_admin(db: Session) -> bool:
    return db.scalar(select(func.count()).select_from(AdminUser)) > 0


@router.get("/status")
def auth_status(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE)
    uid = decode_session_token(get_settings().kaji_secret_key, token) if token else None
    return {
        "setup_required": not _has_admin(db),
        "authenticated": bool(uid and db.get(AdminUser, uid)),
    }


@router.post("/setup", status_code=status.HTTP_201_CREATED)
def setup(body: SetupRequest, response: Response, db: Session = Depends(get_db)):
    if _has_admin(db):
        raise HTTPException(status.HTTP_409_CONFLICT, "Le compte admin existe déjà")
    user = AdminUser(username=body.username, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    _set_cookie(response, user.id)
    return {"username": user.username}


@router.post("/login")
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    if throttle.blocked(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Trop de tentatives, réessaie plus tard")
    user = db.scalar(select(AdminUser).where(AdminUser.username == body.username))
    if not verify_password(body.password, user.password_hash if user else None) or user is None:
        throttle.fail(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Identifiants invalides")
    throttle.reset(ip)
    _set_cookie(response, user.id)
    return {"username": user.username}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")


@router.get("/me")
def me(user: AdminUser = Depends(current_user)):
    return {"username": user.username}
