"""Clé SÉPARÉE des jetons Proxmox personnels (lot #440).

Les jetons des utilisateurs de Kaji sont chiffrés avec `KAJI_TOKEN_KEY`, **pas** avec `KAJI_SECRET_KEY` (qui signe les sessions et chiffre le jeton partagé des connexions) :
compromettre l'une n'ouvre pas l'autre, et la base de Kaji **seule** (ou avec `.env`) ne permet pas de lire un jeton si la clé séparée est ailleurs (`KAJI_TOKEN_KEY_FILE`).

- Dérivation HKDF avec une étiquette propre (`kaji-user-token-v1`) : même une clé identique donnerait une clé de chiffrement différente de celle de `crypto.py`.
- Rotation : `KAJI_TOKEN_KEY` (nouvelle) + `KAJI_TOKEN_KEY_PREVIOUS` (ancienne) ; `MultiFernet` lit avec les deux et écrit avec la première ; `rotate` ré-chiffre tout.
- Aucune valeur secrète n'est jamais renvoyée, journalisée ni placée dans un message d'erreur.
"""
import base64
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .config import MIN_SECRET_KEY_LENGTH, WEAK_SECRET_KEYS, Settings, get_settings

_INFO = b"kaji-user-token-v1"


class TokenKeyError(Exception):
    """Clé absente, trop courte, identique à `KAJI_SECRET_KEY`, ou illisible. Le message ne contient jamais la clé."""


def _fernet(key: str) -> Fernet:
    derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(key.encode())
    return Fernet(base64.urlsafe_b64encode(derived))


def load_key(settings: Settings | None = None) -> str | None:
    """La clé courante (variable ou fichier), ou `None` si la fonction n'est pas configurée. Lève `TokenKeyError` si elle est inutilisable."""
    s = settings or get_settings()
    key = s.kaji_token_key
    if s.kaji_token_key_file:
        try:
            from_file = Path(s.kaji_token_key_file).read_text(encoding="utf-8").strip()
        except OSError as e:
            raise TokenKeyError(f"KAJI_TOKEN_KEY_FILE : fichier illisible ({type(e).__name__})") from e
        if key and key != from_file:
            raise TokenKeyError("KAJI_TOKEN_KEY et KAJI_TOKEN_KEY_FILE sont tous deux définis avec des valeurs différentes : n'en garde qu'un")
        key = from_file
    key = key.strip()
    if not key:
        return None
    _check(key, s)
    return key


def _check(key: str, s: Settings) -> None:
    if key.lower() in WEAK_SECRET_KEYS or len(key) < MIN_SECRET_KEY_LENGTH:
        raise TokenKeyError(f"La clé des jetons personnels est trop courte ou d'exemple : au moins {MIN_SECRET_KEY_LENGTH} caractères aléatoires "
                            "(python3 -c \"import secrets; print(secrets.token_urlsafe(48))\")")
    if key == s.kaji_secret_key:
        raise TokenKeyError("La clé des jetons personnels doit être DIFFÉRENTE de KAJI_SECRET_KEY (c'est tout l'intérêt de la séparer)")


def keys(settings: Settings | None = None) -> list[str]:
    """[courante, précédente] sans doublon ni valeur vide ; vide si la fonction n'est pas configurée."""
    s = settings or get_settings()
    current = load_key(s)
    if current is None:
        return []
    out = [current]
    previous = s.kaji_token_key_previous.strip()
    if previous and previous != current:
        _check(previous, s)
        out.append(previous)
    return out


def _multi(key_list: list[str]) -> MultiFernet:
    if not key_list:
        raise TokenKeyError("Clé des jetons personnels non configurée (KAJI_TOKEN_KEY ou KAJI_TOKEN_KEY_FILE)")
    return MultiFernet([_fernet(k) for k in key_list])


def encrypt(plaintext: str, key_list: list[str] | None = None) -> str:
    return _multi(key_list if key_list is not None else keys()).encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str, key_list: list[str] | None = None) -> str:
    try:
        return _multi(key_list if key_list is not None else keys()).decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise TokenKeyError("Jeton personnel illisible avec la clé configurée") from e


def readable(ciphertext: str | None, key_list: list[str]) -> bool:
    try:
        decrypt(ciphertext or "", key_list)
        return True
    except TokenKeyError:
        return False


def rotate(ciphertext: str, key_list: list[str]) -> str:
    """Ré-chiffre avec la PREMIÈRE clé (la courante) ; lève `TokenKeyError` si aucune des clés ne le lit."""
    try:
        return _multi(key_list).rotate(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise TokenKeyError("Jeton personnel illisible avec les clés fournies") from e
