"""Hachage des mots de passe, jetons de session et limitation des tentatives."""
import ipaddress
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_ph = PasswordHasher()
# Hash factice : on vérifie quand même un mot de passe si l'utilisateur n'existe pas
# pour ne pas révéler son existence par le temps de réponse.
_DUMMY_HASH = _ph.hash("kaji-dummy-password")


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _ph.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, InvalidHashError):
        return False


def _signing_key(secret_key: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"kaji-session-v1").derive(
        secret_key.encode()
    )


def create_session_token(secret_key: str, user_id: int, hours: int, jti: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "jti": jti, "iat": now, "exp": now + timedelta(hours=hours)}
    return jwt.encode(payload, _signing_key(secret_key), algorithm="HS256")


def decode_session(secret_key: str, token: str) -> tuple[int, str] | None:
    """(identifiant utilisateur, identifiant de session), ou None. Un jeton sans jti est refusé."""
    try:
        data = jwt.decode(token, _signing_key(secret_key), algorithms=["HS256"])
        jti = data["jti"]
        if not isinstance(jti, str) or not jti:
            return None
        return int(data["sub"]), jti
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def client_ip(request, trust_proxy: bool = False) -> str:
    """IP du client. Derrière un proxy de confiance : la dernière valeur de X-Forwarded-For (celle qu'il a ajoutée)."""
    if trust_proxy:
        last = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
        try:
            ipaddress.ip_address(last)
            return last
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"


class LoginThrottle:
    """Limite les échecs de connexion par clé (adresse IP, `setup:IP`…), **de façon persistante** (table `login_failures`, lot #446) : un redémarrage de Kaji ne remet pas le compteur à zéro.

    `max_failures` échecs dans la fenêtre `window` (secondes) bloquent la clé ; les échecs plus vieux sont ignorés puis supprimés (la table ne grossit pas : une clé bloquée n'ajoute plus de ligne,
    car les routes refusent avant de vérifier). Ne garde que la clé et l'heure, jamais un identifiant ni un mot de passe. `session_factory` : tests (une autre base)."""

    def __init__(self, max_failures: int = 5, window: int = 300, session_factory=None):
        self.max_failures, self.window = max_failures, window
        self._session_factory = session_factory

    def _session(self):
        if self._session_factory is not None:
            return self._session_factory()
        from sqlalchemy.orm import Session

        from .db import get_engine
        return Session(get_engine())

    def _cutoff(self) -> datetime:
        return datetime.now(timezone.utc) - timedelta(seconds=self.window)

    def blocked(self, key: str) -> bool:
        from sqlalchemy import func, select

        from .models import LoginFailure
        with self._session() as db:
            n = db.scalar(select(func.count()).select_from(LoginFailure).where(LoginFailure.key == key[:80], LoginFailure.ts > self._cutoff()))
        return (n or 0) >= self.max_failures

    def fail(self, key: str) -> None:
        from sqlalchemy import delete

        from .models import LoginFailure
        with self._session() as db:
            db.execute(delete(LoginFailure).where(LoginFailure.ts <= self._cutoff()))          # purge de tout ce qui est hors fenêtre
            db.add(LoginFailure(key=key[:80], ts=datetime.now(timezone.utc)))
            db.commit()

    def reset(self, key: str | None = None) -> None:
        from sqlalchemy import delete

        from .models import LoginFailure
        with self._session() as db:
            db.execute(delete(LoginFailure) if key is None else delete(LoginFailure).where(LoginFailure.key == key[:80]))
            db.commit()


throttle = LoginThrottle()
