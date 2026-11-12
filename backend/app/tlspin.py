"""Épinglage du certificat d'un serveur Proxmox (V1, `docs/securite.md`).

Le certificat par défaut de Proxmox est signé par une autorité propre au cluster : aucune autorité publique ne peut le vérifier, donc `verify_ssl` reste faux dans la plupart des
installations et un attaquant placé sur le réseau pourrait se faire passer pour Proxmox et lire le jeton API. L'épinglage règle cela : l'utilisateur compare l'empreinte SHA-256
affichée à celle de son nœud et la **confirme une fois** ; ensuite Kaji n'accepte plus QUE ce certificat (il sert d'ancre de confiance, chaîne partielle autorisée, sans vérifier le nom).
Si le certificat change (renouvellement, usurpation), les appels échouent avec un message qui l'explique, jusqu'à ce que l'utilisateur épingle le nouveau.
Seul le certificat public est stocké.
"""
import hashlib
import re
import socket
import ssl
from datetime import timezone

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import NameOID

FINGERPRINT = re.compile(r"^([0-9A-F]{2}:){31}[0-9A-F]{2}$")
PROBE_TIMEOUT = 8


def fingerprint_of_der(der: bytes) -> str:
    h = hashlib.sha256(der).hexdigest().upper()
    return ":".join(h[i:i + 2] for i in range(0, 64, 2))


def fingerprint_of_pem(pem: str) -> str | None:
    """Empreinte du certificat PEM stocké ; `None` si le texte n'est pas un certificat (donnée corrompue : l'épinglage est alors ignoré par l'appelant, qui refuse de se connecter)."""
    try:
        cert = x509.load_pem_x509_certificate(pem.encode())
    except ValueError:
        return None
    return fingerprint_of_der(cert.public_bytes(serialization.Encoding.DER))


def pem_of_der(der: bytes) -> str:
    return ssl.DER_cert_to_PEM_cert(der)


def context_for(pem: str) -> ssl.SSLContext:
    """Contexte TLS qui n'accepte QUE ce certificat : il est l'unique ancre de confiance (`VERIFY_X509_PARTIAL_CHAIN` : un certificat feuille peut servir d'ancre), le nom n'est pas vérifié
    (un certificat épinglé est reconnu à son contenu, pas à son nom, et l'adresse d'un nœud est souvent une IP)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    ctx.load_verify_locations(cadata=pem)
    return ctx


def _name(cert_name: x509.Name) -> str | None:
    for oid in (NameOID.COMMON_NAME, NameOID.ORGANIZATION_NAME):
        attrs = cert_name.get_attributes_for_oid(oid)
        if attrs:
            return re.sub(r"[\x00-\x1f\x7f]", "", str(attrs[0].value))[:120]
    return None


def describe(der: bytes) -> dict:
    """Ce que l'utilisateur doit voir pour décider : empreinte, sujet, émetteur, validité. Texte borné, sans caractère de contrôle."""
    cert = x509.load_der_x509_certificate(der)
    return {"fingerprint": fingerprint_of_der(der), "subject": _name(cert.subject), "issuer": _name(cert.issuer),
            "self_signed": cert.subject == cert.issuer,
            "not_before": cert.not_valid_before_utc.astimezone(timezone.utc).isoformat(), "not_after": cert.not_valid_after_utc.astimezone(timezone.utc).isoformat()}


def fetch_der(host: str, port: int) -> bytes:
    """Certificat que le serveur présente MAINTENANT (bloquant : à lancer dans un thread). Aucune vérification : c'est précisément ce qu'on veut montrer. Lève `OSError` en cas d'échec."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=PROBE_TIMEOUT) as raw:
        with ctx.wrap_socket(raw, server_hostname=None) as tls:
            der = tls.getpeercert(binary_form=True)
    if not der:
        raise OSError("aucun certificat présenté")
    return der
