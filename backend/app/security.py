"""Hachage des mots de passe, jetons de session et limitation des tentatives."""
import time
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


def create_session_token(secret_key: str, user_id: int, hours: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(hours=hours)}
    return jwt.encode(payload, _signing_key(secret_key), algorithm="HS256")


def decode_session_token(secret_key: str, token: str) -> int | None:
    try:
        data = jwt.decode(token, _signing_key(secret_key), algorithms=["HS256"])
        return int(data["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


class LoginThrottle:
    """Limite les échecs de connexion par IP (en mémoire)."""

    def __init__(self, max_failures: int = 5, window: int = 300):
        self.max_failures, self.window = max_failures, window
        self._failures: dict[str, list[float]] = {}

    def _recent(self, key: str) -> list[float]:
        now = time.monotonic()
        recent = [t for t in self._failures.get(key, []) if now - t < self.window]
        self._failures[key] = recent
        return recent

    def blocked(self, key: str) -> bool:
        return len(self._recent(key)) >= self.max_failures

    def fail(self, key: str) -> None:
        self._recent(key).append(time.monotonic())

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._failures.clear()
        else:
            self._failures.pop(key, None)


throttle = LoginThrottle()
