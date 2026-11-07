"""Certificat personnalisé d'un nœud : contrôle d'un certificat et de sa clé privée avant tout envoi à Proxmox.

La **clé privée** est un secret : elle n'est jamais journalisée, jamais écrite dans l'audit, jamais renvoyée, jamais reprise dans une
erreur (`SecretStr` + messages fixes). Les contrôles sont faits localement avec `cryptography` ; Proxmox revalide ensuite.
"""
import re
from datetime import datetime, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtensionOID, NameOID
from pydantic import BaseModel, Field, SecretStr

MAX_CHAIN = 32_768
MAX_KEY = 8_192
MAX_CERTS = 6
PEM_CERT = re.compile(r"-----BEGIN CERTIFICATE-----\r?\n[A-Za-z0-9+/=\r\n]+?-----END CERTIFICATE-----")
CUSTOM_FILE = "pveproxy-ssl.pem"


class CertProblem(ValueError):
    """Message fixe, lisible, qui ne cite jamais le contenu du certificat ni de la clé."""


class CustomCert(BaseModel):
    certificates: str = Field(max_length=MAX_CHAIN, description="Certificat puis chaîne, au format PEM")
    key: SecretStr = Field(description="Clé privée PEM non chiffrée")
    confirm: bool = False
    restart: bool = True                  # relancer pveproxy pour servir le nouveau certificat
    replace_existing: bool = False        # écraser un certificat personnalisé déjà en place


class CheckCert(BaseModel):
    certificates: str = Field(max_length=MAX_CHAIN)
    key: SecretStr


def _name(n: x509.Name) -> str:
    cn = n.get_attributes_for_oid(NameOID.COMMON_NAME)
    return cn[0].value[:120] if cn else n.rfc4514_string()[:120]


def analyse(chain_pem: str, key_pem: str, now: datetime | None = None) -> dict:
    """Vérifie la chaîne et la clé ; renvoie un résumé sans secret. Lève `CertProblem` (message fixe) au premier défaut."""
    now = now or datetime.now(timezone.utc)
    blocks = PEM_CERT.findall(chain_pem)
    if not blocks or len(blocks) > MAX_CERTS:
        raise CertProblem(f"Fournis entre 1 et {MAX_CERTS} certificats PEM (le tien d'abord, puis la chaîne)")
    if PEM_CERT.sub("", chain_pem).strip():
        raise CertProblem("Le champ certificats ne doit contenir que des blocs CERTIFICATE (pas de clé, pas de texte)")
    try:
        certs = [x509.load_pem_x509_certificate(b.encode()) for b in blocks]
    except ValueError:
        raise CertProblem("Un certificat est illisible") from None
    if "PRIVATE KEY" not in key_pem or len(key_pem) > MAX_KEY:
        raise CertProblem("La clé privée doit être un bloc PEM")
    try:
        key = serialization.load_pem_private_key(key_pem.encode(), password=None)
    except TypeError:
        raise CertProblem("Clé chiffrée par mot de passe : Proxmox n'en veut pas, fournis-la déchiffrée") from None
    except ValueError:
        raise CertProblem("La clé privée est illisible") from None
    if isinstance(key, rsa.RSAPrivateKey):
        if key.key_size < 2048:
            raise CertProblem("Clé RSA trop courte (2048 bits au minimum)")
        kind = f"RSA {key.key_size}"
    elif isinstance(key, ec.EllipticCurvePrivateKey):
        kind = f"EC {key.curve.name}"
    else:
        raise CertProblem("Type de clé non pris en charge (RSA ou EC)")
    leaf = certs[0]
    spki = lambda pub: pub.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)  # noqa: E731
    if spki(leaf.public_key()) != spki(key.public_key()):
        raise CertProblem("La clé privée ne correspond pas au premier certificat")
    if leaf.not_valid_before_utc > now:
        raise CertProblem("Le certificat n'est pas encore valide")
    if leaf.not_valid_after_utc <= now:
        raise CertProblem("Le certificat est expiré")
    try:
        san = [str(v) for v in leaf.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value.get_values_for_type(x509.DNSName)]
    except x509.ExtensionNotFound:
        san = []
    return {"subject": _name(leaf.subject), "issuer": _name(leaf.issuer), "self_signed": leaf.issuer == leaf.subject,
            "not_after": leaf.not_valid_after_utc.isoformat(), "san": san[:20], "chain_length": len(certs), "key": kind,
            "fingerprint": leaf.fingerprint(hashes.SHA256()).hex(":").upper()}
