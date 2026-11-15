"""TOTP (RFC 6238) pour se connecter à Kaji (lot #444, jalon J2). Bibliothèque standard seulement : pas de dépendance de plus.

Choix : HMAC-SHA1, 6 chiffres, pas de 30 s (le profil que lisent TOUTES les applications d'authentification) ; fenêtre de tolérance d'un pas avant et après (dérive d'horloge) ;
**un code déjà accepté ne l'est jamais deux fois** (anti-rejeu, `last_step`) ; comparaisons en temps constant.
Les codes de secours ont 80 bits (16 caractères) : stockés sous forme d'EMPREINTE à clé (HMAC-SHA256 avec une clé dérivée de `KAJI_SECRET_KEY`), jamais en clair.
"""
import base64
import hashlib
import hmac
import re
import secrets
import struct
import time
from urllib.parse import quote

STEP = 30
DIGITS = 6
WINDOW = 1                                   # un pas avant, un pas après
RECOVERY_COUNT = 10
_CODE = re.compile(r"[0-9]{6}")
_RECOVERY = re.compile(r"[A-Z2-7]{16}")


def generate_secret() -> str:
    """Secret de 160 bits en base32, sans remplissage (le format des applications d'authentification)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    pad = "=" * (-len(secret) % 8)
    return base64.b32decode(secret.upper() + pad)


def code_at(secret: str, step: int, digits: int = DIGITS) -> str:
    """Le code du pas `step` (RFC 4226 / 6238)."""
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % (10 ** digits)).zfill(digits)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP)


def looks_like_code(text: str) -> bool:
    return bool(_CODE.fullmatch(normalize(text)))


def normalize(text: str) -> str:
    """Espaces et tirets ignorés (les applications affichent « 123 456 », les codes de secours « ABCD-EFGH-… »), majuscules."""
    return re.sub(r"[\s-]", "", text or "").upper()


def verify(secret: str, text: str, *, last_step: int = 0, now: float | None = None) -> int | None:
    """Le pas du code s'il est valide ET plus récent que le dernier accepté, sinon `None`. Parcourt toute la fenêtre (temps constant par pas)."""
    candidate = normalize(text)
    if not _CODE.fullmatch(candidate):
        return None
    base = current_step(now)
    found = None
    for step in range(base - WINDOW, base + WINDOW + 1):
        if hmac.compare_digest(code_at(secret, step), candidate) and step > last_step:
            found = step
    return found


def otpauth_uri(secret: str, account: str, issuer: str = "Kaji") -> str:
    label = f"{quote(issuer, safe='')}:{quote(account, safe='')}"
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer, safe='')}&algorithm=SHA1&digits={DIGITS}&period={STEP}"


def new_recovery_codes(count: int = RECOVERY_COUNT) -> list[str]:
    """`count` codes de secours de 80 bits, présentés par groupes de 4 (`ABCD-EFGH-IJKL-MNOP`)."""
    out = []
    for _ in range(count):
        raw = base64.b32encode(secrets.token_bytes(10)).decode()          # 80 bits = 16 caractères base32, sans remplissage
        out.append("-".join(raw[i:i + 4] for i in range(0, 16, 4)))
    return out


def looks_like_recovery(text: str) -> bool:
    return bool(_RECOVERY.fullmatch(normalize(text)))


def recovery_hash(secret_key: str, code: str) -> str:
    """Empreinte d'un code de secours (HMAC-SHA256, clé dérivée de KAJI_SECRET_KEY : une base volée seule ne permet pas de deviner un code)."""
    key = hmac.new(secret_key.encode(), b"kaji-totp-recovery-v1", hashlib.sha256).digest()
    return hmac.new(key, normalize(code).encode(), hashlib.sha256).hexdigest()
