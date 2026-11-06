"""Chiffrement des secrets au repos (tokens API Proxmox)."""
import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_INFO = b"kaji-token-encryption-v1"


def _fernet(secret_key: str) -> Fernet:
    if not secret_key or secret_key == "changeme":
        raise ValueError("KAJI_SECRET_KEY doit être défini avec une valeur aléatoire")
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(
        secret_key.encode()
    )
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(secret_key: str, plaintext: str) -> str:
    return _fernet(secret_key).encrypt(plaintext.encode()).decode()


def decrypt(secret_key: str, ciphertext: str) -> str:
    try:
        return _fernet(secret_key).decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise ValueError("Déchiffrement impossible : clé invalide ou donnée corrompue") from e
