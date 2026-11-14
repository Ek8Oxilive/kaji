"""Mon jeton Proxmox (lot #440, option A du cadrage) : chaque utilisateur de Kaji enregistre SON jeton pour chaque connexion.

`GET /api/me/proxmox-tokens` : l'état pour chaque connexion (jamais un secret). `PUT /api/me/proxmox-tokens/{conn_id}` : enregistre (après contrôle chez Proxmox).
`DELETE /api/me/proxmox-tokens/{conn_id}` : retire. Ouvert à tous les rôles de Kaji (c'est la personne qui gère SON propre jeton) ; les droits réels restent ceux que Proxmox
donne à ce jeton. Le secret est chiffré avec la clé SÉPARÉE (`app/tokenkey.py`), jamais renvoyé, journalisé, ni recopié dans une erreur.
"""
import re
from datetime import date, datetime, time, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, tokenkey
from ..config import get_settings
from ..db import get_db
from ..deps import Factory, get_base_client_factory
from ..models import AdminUser, Connection, UserToken
from .auth import current_user
from .cluster import http_error
from .connections import _get_or_404

router = APIRouter(prefix="/api/me/proxmox-tokens", tags=["me"], dependencies=[Depends(current_user)])

USERID = re.compile(r"[A-Za-z0-9._-]{1,64}@[A-Za-z0-9._-]{1,32}")
TOKENID = re.compile(r"[A-Za-z][A-Za-z0-9._-]{0,63}")
SECRET = re.compile(r"\S{8,200}")
EXPIRING_SOON_DAYS = 7
FORBIDDEN_USERS = frozenset({"root@pam"})            # règle du dépôt : jamais le jeton de root@pam (droits sans limite, hors du contrôle de Kaji)


class TokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pve_user: str = Field(max_length=100, description="ex. alice@pve")
    token_id: str = Field(max_length=64, description="la partie après le « ! »")
    secret: SecretStr
    expires_at: date | None = Field(default=None, description="requis si Proxmox ne dit pas lui-même quand le jeton expire")
    privsep: bool = Field(default=True, description="le jeton a les privilèges séparés (obligatoire)")

    @field_validator("pve_user")
    @classmethod
    def _user(cls, v: str) -> str:
        if not USERID.fullmatch(v):
            raise ValueError("compte Proxmox invalide (attendu : nom@realm)")
        return v

    @field_validator("token_id")
    @classmethod
    def _tid(cls, v: str) -> str:
        if not TOKENID.fullmatch(v):
            raise ValueError("identifiant de jeton invalide")
        return v

    @field_validator("secret")
    @classmethod
    def _secret(cls, v: SecretStr) -> SecretStr:
        if not SECRET.fullmatch(v.get_secret_value()):
            raise ValueError("secret invalide (8 à 200 caractères, sans espace)")
        return v


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _state(t: UserToken | None, now: datetime) -> str:
    if t is None:
        return "none"
    if _aware(t.expires_at) <= now:
        return "expired"
    if t.refused_at is not None:
        return "refused"
    return "expiring" if _aware(t.expires_at) - now <= timedelta(days=EXPIRING_SOON_DAYS) else "ok"


def _view(conn: Connection, t: UserToken | None, now: datetime) -> dict:
    out = {"conn_id": conn.id, "name": conn.name, "state": _state(t, now), "pve_user": None, "token_id": None, "expires_at": None,
           "days_left": None, "privsep": None, "verified": None}
    if t is not None:
        out.update(pve_user=t.pve_user, token_id=t.token_id, expires_at=_aware(t.expires_at).isoformat(), privsep=t.privsep, verified=t.verified,
                   days_left=max(0, (_aware(t.expires_at) - now).days))
    return out


def _key_problem() -> str | None:
    try:
        return None if tokenkey.keys() else "Les jetons personnels sont désactivés : l'administrateur de Kaji doit définir KAJI_TOKEN_KEY (ou KAJI_TOKEN_KEY_FILE), distincte de KAJI_SECRET_KEY."
    except tokenkey.TokenKeyError as e:
        return str(e)


@router.get("")
def list_tokens(db: Session = Depends(get_db), user: AdminUser = Depends(current_user)):
    s, now = get_settings(), datetime.now(timezone.utc)
    mine = {t.conn_id: t for t in db.scalars(select(UserToken).where(UserToken.user_id == user.id))}
    problem = _key_problem()
    return {"enabled": problem is None, "problem": problem, "required": s.kaji_require_user_token, "max_days": s.kaji_user_token_max_days,
            "connections": [_view(c, mine.get(c.id), now) for c in db.scalars(select(Connection).order_by(Connection.name))]}


def _deadline(day: date) -> datetime:
    return datetime.combine(day, time(23, 59, 59), tzinfo=timezone.utc)


def _refuse(db: Session, user: AdminUser, conn_id: int, target: str, detail: str, code: int = 422):
    audit.record(db, username=user.username, connection_id=conn_id, action="user-token-set", target=target[:200], status="error", detail=detail)
    raise HTTPException(code, detail)


async def _inspect(base: Factory, conn: Connection, body: TokenIn):
    """Interroge Proxmox AVEC le jeton à enregistrer. Renvoie `info` = `{"privsep": bool, "expire": epoch|0}` si Proxmox laisse le jeton se lire lui-même, sinon `None`.
    Lève `HTTPException` : 422 si Proxmox refuse le jeton (sans jamais recopier une valeur saisie), l'erreur habituelle si Proxmox est injoignable."""
    client = base(host=conn.host, port=conn.port, user=body.pve_user, token_id=body.token_id, token_secret=body.secret.get_secret_value(),
                  verify_ssl=conn.verify_ssl, pinned_cert=conn.tls_cert_pem or None)
    try:
        try:
            await client.get("/version")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise HTTPException(422, "Proxmox refuse ce jeton (identifiant ou secret incorrect, jeton expiré ou supprimé).")
            raise http_error(e)
        except httpx.HTTPError as e:
            raise http_error(e)
        try:
            data = await client.get(f"/access/users/{body.pve_user}/token/{body.token_id}")
        except httpx.HTTPError:
            return None                                     # Proxmox ne laisse pas ce jeton se décrire : on s'en tient à ce qui est déclaré
        if not isinstance(data, dict):
            return None
        privsep, expire = data.get("privsep"), data.get("expire")
        if isinstance(privsep, bool) or privsep not in (0, 1, "0", "1") or isinstance(expire, bool) or not isinstance(expire, (int, str)) or not str(expire).isdigit():
            return None                                     # réponse inattendue : jamais « vérifié » sans preuve
        return {"privsep": str(privsep) == "1", "expire": int(expire)}
    finally:
        await client.aclose()


@router.put("/{conn_id}")
async def set_token(body: TokenIn, conn_id: int = Path(ge=1), db: Session = Depends(get_db), user: AdminUser = Depends(current_user),
                    base: Factory = Depends(get_base_client_factory)):
    conn = _get_or_404(db, conn_id)
    target = f"{body.pve_user}!{body.token_id}"
    problem = _key_problem()
    if problem:
        _refuse(db, user, conn_id, target, problem, status.HTTP_409_CONFLICT)
    if body.pve_user.lower() in FORBIDDEN_USERS:
        _refuse(db, user, conn_id, target, "Le jeton de root@pam n'est jamais accepté : crée un compte dédié avec les seuls droits nécessaires.")
    if (body.pve_user, body.token_id) == (conn.user, conn.token_id):
        _refuse(db, user, conn_id, target, "C'est le jeton PARTAGÉ de Kaji : enregistre TON jeton personnel (un autre jeton, créé pour toi).")
    if not body.privsep:
        _refuse(db, user, conn_id, target, "Le jeton doit avoir les privilèges séparés : sans cela il a TOUS les droits de ton compte. Recrée-le avec « Privilege Separation » coché.")
    s, now = get_settings(), datetime.now(timezone.utc)
    limit = now + timedelta(days=s.kaji_user_token_max_days)
    info = await _inspect(base, conn, body)
    verified = info is not None
    if info is not None:
        if not info["privsep"]:
            _refuse(db, user, conn_id, target, "Proxmox indique que ce jeton n'a PAS les privilèges séparés : il aurait tous les droits de ton compte. Recrée-le avec « Privilege Separation » coché.")
        if info["expire"] == 0:
            _refuse(db, user, conn_id, target, "Ce jeton n'a pas de date d'expiration chez Proxmox : recrée-le avec une expiration.")
        expires = datetime.fromtimestamp(info["expire"], tz=timezone.utc)
        if body.expires_at is not None:
            expires = min(expires, _deadline(body.expires_at))
    elif body.expires_at is not None:
        expires = _deadline(body.expires_at)
    else:
        _refuse(db, user, conn_id, target, "Proxmox ne dit pas quand ce jeton expire : indique sa date d'expiration (expires_at).")
    if expires <= now:
        _refuse(db, user, conn_id, target, "Ce jeton est déjà expiré.")
    if expires > limit:
        _refuse(db, user, conn_id, target, f"Expiration trop lointaine : au plus {s.kaji_user_token_max_days} jours (réglage KAJI_USER_TOKEN_MAX_DAYS).")
    enc = tokenkey.encrypt(body.secret.get_secret_value())
    row = db.scalars(select(UserToken).where(UserToken.user_id == user.id, UserToken.conn_id == conn_id)).first()
    if row is None:
        row = UserToken(user_id=user.id, conn_id=conn_id)
        db.add(row)
    row.pve_user, row.token_id, row.secret_enc, row.expires_at = body.pve_user, body.token_id, enc, expires
    row.privsep, row.verified, row.refused_at, row.created_at = True, verified, None, now
    db.commit()
    audit.record(db, username=user.username, connection_id=conn_id, action="user-token-set", target=target, status="started",
                 detail=f"expire le {expires.date().isoformat()}, contrôlé par Proxmox : {'oui' if verified else 'non (déclaré)'}")
    return _view(conn, row, now)


@router.delete("/{conn_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_token(conn_id: int = Path(ge=1), db: Session = Depends(get_db), user: AdminUser = Depends(current_user)):
    _get_or_404(db, conn_id)
    row = db.scalars(select(UserToken).where(UserToken.user_id == user.id, UserToken.conn_id == conn_id)).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucun jeton personnel pour cette connexion")
    target = f"{row.pve_user}!{row.token_id}"
    db.delete(row)
    db.commit()
    audit.record(db, username=user.username, connection_id=conn_id, action="user-token-removed", target=target, status="started", detail="jeton personnel retiré de Kaji (il reste valable chez Proxmox)")
