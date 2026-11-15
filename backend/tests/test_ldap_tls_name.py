"""Nom attendu dans le certificat de l'annuaire (`KAJI_LDAP_TLS_SERVER_NAME`) : on se connecte par une adresse IP et on exige le NOM du certificat. VRAIS échanges TLS avec une autorité privée de test."""
import datetime
import socket
import ssl
import threading
import time

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from ldap3 import Connection
from ldap3.core.exceptions import LDAPExceptionError

from app import ldaplogin
from app.config import get_settings

NOW = datetime.datetime.now(datetime.timezone.utc)


def _cert(subject, issuer, key, signing_key, *, ca=False, dns=None):
    b = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(key.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(NOW - datetime.timedelta(days=1)).not_valid_after(NOW + datetime.timedelta(days=1))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    b = b.add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
    if ca:                                                                                           # la vérification stricte exige l'usage de clé d'une autorité
        b = b.add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
    if signing_key is not key:                                                                       # la feuille porte l'identifiant de clé de son autorité (exigé par la vérification stricte, comme un vrai certificat d'AD)
        b = b.add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(signing_key.public_key()), critical=False)
    if dns:
        b = b.add_extension(x509.SubjectAlternativeName([x509.DNSName(dns)]), critical=False)
    return b.sign(signing_key, hashes.SHA256())


@pytest.fixture
def pki(tmp_path):
    ca_key, leaf_key = rsa.generate_private_key(65537, 2048), rsa.generate_private_key(65537, 2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Autorite de test")])
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ad.test")])
    ca = _cert(ca_name, ca_name, ca_key, ca_key, ca=True)
    leaf = _cert(leaf_name, ca_name, leaf_key, ca_key, dns="ad.test")
    pem = serialization.Encoding.PEM
    (tmp_path / "ca.pem").write_bytes(ca.public_bytes(pem))
    (tmp_path / "leaf.pem").write_bytes(leaf.public_bytes(pem))
    (tmp_path / "leaf.key").write_bytes(leaf_key.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return tmp_path


@pytest.fixture
def tls_server(pki):
    """Un serveur TLS local (certificat au nom ad.test, signé par l'autorité de test) qui accepte l'échange puis ferme."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(pki / "leaf.pem", pki / "leaf.key")
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    srv.settimeout(5)
    stop = threading.Event()

    def run():
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            try:
                tls = ctx.wrap_socket(conn, server_side=True)
                time.sleep(0.2)
                tls.close()
            except Exception:
                conn.close()
    t = threading.Thread(target=run, daemon=True)
    t.start()
    yield srv.getsockname()[1]
    stop.set()
    srv.close()


def settings(pki, port, name="", ca=True):
    return get_settings().model_copy(update={"kaji_ldap_url": f"ldaps://127.0.0.1:{port}", "kaji_ldap_ca_file": str(pki / "ca.pem") if ca else "", "kaji_ldap_tls_server_name": name})


def opens(s) -> bool:
    c = Connection(ldaplogin._server(s), auto_bind=False)
    try:
        c.open(read_server_info=False)                                                               # lève une erreur si l'échange TLS ou la vérification du nom échoue
        return not c.closed
    except LDAPExceptionError:
        return False
    finally:
        try:
            c.unbind()
        except Exception:
            pass


def test_the_certificate_name_is_enough_when_the_address_is_an_ip(pki, tls_server):
    assert opens(settings(pki, tls_server, name="ad.test")) is True


def test_without_the_name_an_ip_address_is_refused_because_the_certificate_does_not_carry_it(pki, tls_server):
    assert opens(settings(pki, tls_server, name="")) is False


def test_another_name_is_refused(pki, tls_server):
    assert opens(settings(pki, tls_server, name="autre.test")) is False


def test_the_authority_is_still_required_even_with_the_right_name(pki, tls_server):
    assert opens(settings(pki, tls_server, name="ad.test", ca=False)) is False


def test_the_tls_name_is_handed_to_the_library_and_empty_means_no_extra_name(pki):
    assert ldaplogin._server(settings(pki, 636, name="ad.test")).tls.valid_names == ["ad.test"]
    assert ldaplogin._server(settings(pki, 636, name="")).tls.valid_names is None


@pytest.mark.parametrize("name", ["*", "*.test", "ad test", "ad.test\n", "-ad.test", "ad.test-", "a" * 300, "ad_test", "ad.test/x", "ad.test;x", " "])
def test_unsafe_names_are_refused_by_the_configuration_check(pki, name):
    """Le joker `*` ferait accepter n'importe quel nom par ldap3 : il est refusé, comme tout ce qui n'est pas un nom DNS."""
    s = settings(pki, 636, name=name).model_copy(update={"kaji_ldap_base_dn": "dc=x", "kaji_ldap_bind_dn": "cn=x", "kaji_ldap_bind_password": "pw"})
    assert ldaplogin.configuration_problem(s) == "nom attendu dans le certificat invalide"


@pytest.mark.parametrize("name", ["", "ad.test", "WIN-8FOU54ASDHT.homelab.local", "a", "a1"])
def test_valid_names_pass_the_configuration_check(pki, name):
    s = settings(pki, 636, name=name).model_copy(update={"kaji_ldap_base_dn": "dc=x", "kaji_ldap_bind_dn": "cn=x", "kaji_ldap_bind_password": "pw"})
    assert ldaplogin.configuration_problem(s) is None
