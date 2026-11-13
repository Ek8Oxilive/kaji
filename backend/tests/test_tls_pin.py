"""Épinglage du certificat Proxmox : VRAIS handshakes TLS contre un serveur local (pas de faux transport : c'est la vérification elle-même qu'on teste)."""
import datetime
import http.server
import json
import ssl
import tempfile
import threading
from pathlib import Path

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app import tlspin
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"


def make_cert(cn, issuer=None, days=30):
    """`(certificat, clé)` ; auto-signé sauf si `issuer=(certificat, clé)`."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.datetime.now(datetime.timezone.utc)
    ca_cert, ca_key = issuer if issuer else (None, key)
    b = (x509.CertificateBuilder().subject_name(name).issuer_name(ca_cert.subject if ca_cert else name).public_key(key.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=days))
         .add_extension(x509.BasicConstraints(ca=issuer is None, path_length=None), critical=True))
    return b.sign(ca_key, hashes.SHA256()), key


def pem(cert):
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def der(cert):
    return cert.public_bytes(serialization.Encoding.DER)


class TlsServer:
    """Serveur HTTPS local qui répond comme `/version` de Proxmox ; le certificat se change à chaud."""

    def __init__(self, cert, key, chain=()):
        self.d = tempfile.mkdtemp()
        self.set(cert, key, chain)

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self_):  # noqa: N805
                body = json.dumps({"data": {"version": "9.1", "release": "9"}}).encode()
                self_.send_response(200)
                self_.send_header("Content-Type", "application/json")
                self_.send_header("Content-Length", str(len(body)))
                self_.end_headers()
                self_.wfile.write(body)

            def log_message(self_, *a):  # noqa: N805
                pass

        class Quiet(http.server.ThreadingHTTPServer):
            def handle_error(self_, request, client_address):  # noqa: N805 — une poignée de main refusée est le comportement testé, pas une erreur
                pass

        self.httpd = Quiet(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        self.httpd.socket = _SwapSocket(self.httpd.socket, self)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def set(self, cert, key, chain=()):
        f = Path(self.d) / "chain.pem"
        f.write_text(pem(cert) + "".join(pem(c) for c in chain))
        k = Path(self.d) / "key.pem"
        k.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(f, k)
        self.ctx = ctx

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class _SwapSocket:
    """Enveloppe le socket d'écoute : chaque connexion acceptée est chiffrée avec le contexte COURANT (permet de changer de certificat sans changer de port)."""

    def __init__(self, sock, server):
        self._s, self._srv = sock, server

    def accept(self):
        conn, addr = self._s.accept()
        try:
            return self._srv.ctx.wrap_socket(conn, server_side=True), addr
        except (ssl.SSLError, OSError):
            conn.close()
            raise

    def __getattr__(self, n):
        return getattr(self._s, n)


@pytest.fixture
def server():
    cert, key = make_cert("pve-test")
    s = TlsServer(cert, key)
    s.cert = cert
    yield s
    s.close()


async def fetch_version(port, **kw):
    c = ProxmoxClient("127.0.0.1", "kaji@pve", "kaji", "x", port=port, **kw)
    try:
        return await c.get("/version")
    finally:
        await c.aclose()


# ---------------------------------------------------------------- le client
@pytest.mark.anyio
async def test_the_pinned_certificate_is_accepted_and_nothing_else(server):
    assert (await fetch_version(server.port, pinned_cert=pem(server.cert)))["version"] == "9.1"
    other, _ = make_cert("autre")
    with pytest.raises(httpx.ConnectError) as e:
        await fetch_version(server.port, pinned_cert=pem(other))
    assert "CERTIFICATE" in str(e.value).upper()


@pytest.mark.anyio
async def test_the_pin_wins_over_verify_ssl_false(server):
    other, _ = make_cert("autre")
    with pytest.raises(httpx.ConnectError):
        await fetch_version(server.port, verify_ssl=False, pinned_cert=pem(other))      # sans épingle, verify_ssl=False accepterait n'importe quoi
    assert (await fetch_version(server.port, verify_ssl=False))["version"] == "9.1"


@pytest.mark.anyio
async def test_a_certificate_that_changes_is_refused(server):
    pinned = pem(server.cert)
    assert (await fetch_version(server.port, pinned_cert=pinned))["version"] == "9.1"
    new, key = make_cert("pve-test")                                                       # même nom, autre clé : usurpation ou renouvellement
    server.set(new, key)
    with pytest.raises(httpx.ConnectError):
        await fetch_version(server.port, pinned_cert=pinned)


@pytest.mark.anyio
async def test_a_leaf_signed_by_a_private_authority_can_be_pinned():
    ca, ca_key = make_cert("pve-root-ca")
    leaf, leaf_key = make_cert("pve-leaf", issuer=(ca, ca_key))
    s = TlsServer(leaf, leaf_key, chain=())
    try:
        assert (await fetch_version(s.port, pinned_cert=pem(leaf)))["version"] == "9.1"      # la feuille seule sert d'ancre (chaîne partielle)
        other, _ = make_cert("autre")
        with pytest.raises(httpx.ConnectError):
            await fetch_version(s.port, pinned_cert=pem(other))
    finally:
        s.close()


@pytest.mark.anyio
async def test_the_pin_is_checked_by_content_not_by_name(server):
    c = ProxmoxClient("localhost", "kaji@pve", "kaji", "x", port=server.port, pinned_cert=pem(server.cert))      # le nom `localhost` n'est pas dans le certificat
    try:
        assert (await c.get("/version"))["version"] == "9.1"
    finally:
        await c.aclose()


def test_the_websocket_context_uses_the_pin(server):
    other, _ = make_cert("autre")
    c = ProxmoxClient("127.0.0.1", "kaji@pve", "kaji", "x", port=server.port, pinned_cert=pem(server.cert))
    _, _, ctx = c.ws_target("/nodes/x/vncwebsocket")
    assert ctx.verify_mode == ssl.CERT_REQUIRED and not ctx.check_hostname
    c2 = ProxmoxClient("127.0.0.1", "kaji@pve", "kaji", "x", port=server.port, verify_ssl=False)
    assert c2.ws_target("/x")[2].verify_mode == ssl.CERT_NONE


# ---------------------------------------------------------------- helpers
def test_fingerprint_describe_and_pem_roundtrip():
    cert, _ = make_cert("pve-test")
    fp = tlspin.fingerprint_of_der(der(cert))
    assert tlspin.FINGERPRINT.fullmatch(fp) and tlspin.fingerprint_of_pem(pem(cert)) == fp == tlspin.fingerprint_of_pem(tlspin.pem_of_der(der(cert)))
    d = tlspin.describe(der(cert))
    assert d["fingerprint"] == fp and d["subject"] == "pve-test" and d["self_signed"] is True and d["not_after"] > d["not_before"]
    assert tlspin.fingerprint_of_pem("pas un certificat") is None


def test_describe_strips_control_characters():
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "a" * 20 + "\x07\x1b[31m" + "b" * 20)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(1).not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=1)).sign(key, hashes.SHA256()))
    s = tlspin.describe(der(cert))["subject"]
    assert s == "a" * 20 + "[31m" + "b" * 20


# ---------------------------------------------------------------- l'API
@pytest.fixture
def api(client, server):
    app.dependency_overrides[get_client_factory] = lambda: ProxmoxClient          # VRAIS clients : c'est le TLS qu'on teste
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json={"name": "lab", "host": "127.0.0.1", "port": server.port, "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def tls(c, cid):
    return c.get(f"/api/connections/{cid}/tls").json()


def pin(c, cid, fp, **kw):
    return c.put(f"/api/connections/{cid}/tls", json={"fingerprint": fp, "confirm": True, **kw})


def audit_rows(c):
    return [(a["action"], a["status"], a.get("detail") or "") for a in c.get("/api/audit").json()]


def test_status_shows_the_presented_certificate_and_that_nothing_is_pinned(api, server):
    c, cid = api
    j = tls(c, cid)
    assert j["reachable"] and j["pinned"] is False and j["matches"] is None and j["fingerprint"] == tlspin.fingerprint_of_der(der(server.cert))
    assert j["subject"] == "pve-test" and j["self_signed"] is True and SECRET not in json.dumps(j)
    conn = c.get(f"/api/connections/{cid}").json()
    assert conn["tls_pinned"] is False and conn["tls_fingerprint"] is None


def test_pin_requires_confirm_and_the_exact_fingerprint(api, server):
    c, cid = api
    fp = tlspin.fingerprint_of_der(der(server.cert))
    assert c.put(f"/api/connections/{cid}/tls", json={"fingerprint": fp}).status_code == 400
    assert c.put(f"/api/connections/{cid}/tls", json={"fingerprint": fp, "confirm": "yes"}).status_code == 422
    for bad in ("", fp.lower(), fp[:-3], fp + ":AA", "ZZ" + fp[2:], fp + "\n"):
        assert pin(c, cid, bad).status_code == 422, bad
    other = tlspin.fingerprint_of_der(der(make_cert("autre")[0]))
    r = pin(c, cid, other)
    assert r.status_code == 409 and "plus celui que tu as vu" in r.json()["detail"]
    assert tls(c, cid)["pinned"] is False


def test_pin_then_the_connection_only_works_with_that_certificate(api, server):
    c, cid = api
    fp = tlspin.fingerprint_of_der(der(server.cert))
    r = pin(c, cid, fp)
    assert r.status_code == 200 and r.json()["pinned"] is True and r.json()["matches"] is True and r.json()["pinned_fingerprint"] == fp
    assert c.get(f"/api/connections/{cid}").json()["tls_fingerprint"] == fp
    assert c.post(f"/api/connections/{cid}/test").json()["ok"] is True
    new, key = make_cert("pve-test")                                                      # le serveur change de certificat
    server.set(new, key)
    j = tls(c, cid)
    assert j["pinned"] is True and j["matches"] is False and j["fingerprint"] != fp
    t = c.post(f"/api/connections/{cid}/test").json()
    assert t["ok"] is False
    r = c.get(f"/api/connections/{cid}/nodes")
    assert r.status_code == 502 and "épinglé" in r.json()["detail"] and SECRET not in r.text


def test_repinning_after_a_certificate_change_needs_the_new_fingerprint(api, server):
    c, cid = api
    pin(c, cid, tlspin.fingerprint_of_der(der(server.cert)))
    new, key = make_cert("pve-test")
    server.set(new, key)
    r = pin(c, cid, tlspin.fingerprint_of_der(der(new)))
    assert r.status_code == 200 and r.json()["matches"] is True
    assert c.post(f"/api/connections/{cid}/test").json()["ok"] is True


def test_unpin_needs_confirm_and_restores_the_old_behaviour(api, server):
    c, cid = api
    assert c.delete(f"/api/connections/{cid}/tls", params={"confirm": "true"}).status_code == 409           # rien d'épinglé
    pin(c, cid, tlspin.fingerprint_of_der(der(server.cert)))
    assert c.delete(f"/api/connections/{cid}/tls").status_code == 400
    assert tls(c, cid)["pinned"] is True
    r = c.delete(f"/api/connections/{cid}/tls", params={"confirm": "true"})
    assert r.status_code == 200 and r.json()["pinned"] is False
    new, key = make_cert("autre")
    server.set(new, key)
    assert c.post(f"/api/connections/{cid}/test").json()["ok"] is True                                       # `verify_ssl` faux : comme avant


def test_changing_the_host_or_port_drops_the_pin(api, server):
    c, cid = api
    pin(c, cid, tlspin.fingerprint_of_der(der(server.cert)))
    assert c.patch(f"/api/connections/{cid}", json={"name": "renommée"}).json()["tls_pinned"] is True         # un autre champ ne le touche pas
    assert c.patch(f"/api/connections/{cid}", json={"token_secret": "autre-secret"}).json()["tls_pinned"] is True
    r = c.patch(f"/api/connections/{cid}", json={"port": server.port + 1})
    assert r.status_code == 200 and r.json()["tls_pinned"] is False and r.json()["tls_fingerprint"] is None
    r = c.patch(f"/api/connections/{cid}", json={"port": server.port})
    assert r.json()["tls_pinned"] is False


def test_an_unreachable_server_is_reported_without_details(client):
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json={"name": "x", "host": "127.0.0.1", "port": 1, "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}).json()["id"]
    j = client.get(f"/api/connections/{cid}/tls").json()
    assert j["reachable"] is False and j["pinned"] is False and "fingerprint" not in j
    r = client.put(f"/api/connections/{cid}/tls", json={"fingerprint": "AA:" * 31 + "AA", "confirm": True})
    assert r.status_code == 502 and "Connection" not in r.text and "refused" not in r.text.lower()


def test_unknown_connection_and_no_session(client):
    for m in ("get", "put", "delete"):
        assert getattr(client, m)("/api/connections/1/tls").status_code == 401
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    assert client.get("/api/connections/999/tls").status_code == 404
    assert client.put("/api/connections/999/tls", json={"fingerprint": "AA:" * 31 + "AA", "confirm": True}).status_code == 404
    assert client.delete("/api/connections/999/tls", params={"confirm": "true"}).status_code == 404


def test_every_pin_action_is_audited_with_the_public_fingerprint_only(api, server):
    c, cid = api
    fp = tlspin.fingerprint_of_der(der(server.cert))
    c.put(f"/api/connections/{cid}/tls", json={"fingerprint": fp})                      # refus : pas de confirmation
    pin(c, cid, fp)
    c.delete(f"/api/connections/{cid}/tls", params={"confirm": "true"})
    rows = audit_rows(c)
    assert ("tls-pin", "error", "confirmation absente") in rows and ("tls-pin", "started", f"empreinte {fp}") in rows and ("tls-unpin", "started", "épingle retirée") in rows
    text = c.get("/api/audit").text
    assert SECRET not in text and "BEGIN CERTIFICATE" not in text
    assert "BEGIN CERTIFICATE" not in json.dumps(c.get(f"/api/connections/{cid}").json())             # le PEM n'est jamais renvoyé


def test_the_stored_certificate_is_public_only(api, server):
    c, cid = api
    pin(c, cid, tlspin.fingerprint_of_der(der(server.cert)))
    from app.db import get_engine
    from sqlalchemy import text
    with get_engine().connect() as conn:
        stored = conn.execute(text("SELECT tls_cert_pem FROM connections")).scalar()
    assert stored.startswith("-----BEGIN CERTIFICATE-----") and "PRIVATE" not in stored


# ---------------------------------------------------------------- migration de la base
def test_the_real_migration_adds_the_column_to_an_existing_database(tmp_path):
    """Une base déployée AVANT l'épinglage : la colonne est ajoutée, les connexions restent intactes (et sans épingle), une sauvegarde est faite."""
    from sqlalchemy import create_engine, inspect, text

    from app.db import Base
    from app.migrations import MIGRATIONS, run_migrations
    e = create_engine(f"sqlite:///{tmp_path / 'kaji.db'}")
    from app import models  # noqa: F401
    Base.metadata.create_all(e)
    with e.begin() as c:
        c.execute(text("ALTER TABLE connections DROP COLUMN tls_cert_pem"))
        c.execute(text("INSERT INTO connections (name, host, port, user, token_id, token_secret_enc, verify_ssl, created_at) VALUES ('perso', '10.0.0.1', 8006, 'kaji@pve', 'kaji', 'chiffre', 0, '2026-01-01')"))
    assert "tls_cert_pem" not in {col["name"] for col in inspect(e).get_columns("connections")}
    with e.begin() as c:
        c.execute(text("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"))
        c.execute(text("INSERT INTO schema_migrations VALUES (1, 'schéma initial', '2026-01-01')"))
    r = run_migrations(e)
    assert r["applied"] == [2, 3] and r["backup"] is not None and MIGRATIONS[-1].version == 3
    assert "tls_cert_pem" in {col["name"] for col in inspect(e).get_columns("connections")}
    with e.connect() as c:
        row = c.execute(text("SELECT name, host, tls_cert_pem FROM connections")).one()
    assert tuple(row) == ("perso", "10.0.0.1", None)


# ---------------------------------------------------------------- l'épingle suit TOUS les clients de la connexion
def test_the_admin_session_clients_also_receive_the_pin(client, server):
    """La session administrateur (jeton d'écriture des droits) ne doit pas contourner l'épingle : les deux endroits qui construisent un client la transmettent."""
    seen = []

    def factory(**kw):
        seen.append(kw)
        return ProxmoxClient(**kw, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": {}})))

    app.dependency_overrides[get_client_factory] = lambda: factory
    try:
        client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
        cid = client.post("/api/connections", json={"name": "lab", "host": "127.0.0.1", "port": server.port, "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}).json()["id"]
        pin(client, cid, tlspin.fingerprint_of_der(der(server.cert)))
        r = client.post(f"/api/connections/{cid}/admin-session", json={"user": "admin@pve", "token_id": "kaji-admin", "secret": "12345678-1234-1234-1234-123456789012"})
        assert r.status_code in (201, 502, 403, 422), r.text
        assert seen and seen[-1]["pinned_cert"] == pem(server.cert) and seen[-1]["token_id"] == "kaji-admin"
        from app.db import get_engine
        from sqlalchemy.orm import Session

        from app.routers.admin_session import admin_client
        from types import SimpleNamespace
        with Session(get_engine()) as db:
            c = admin_client(db, factory, cid, SimpleNamespace(user="admin@pve", token_id="kaji-admin", secret=SimpleNamespace(get_secret_value=lambda: "x")))
        assert seen[-1]["pinned_cert"] == pem(server.cert) and c is not None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_a_pin_also_wins_when_verify_ssl_is_true(server):
    """`verify_ssl=True` + épingle : l'épingle prime (un certificat auto-signé n'est pas dans le magasin du système, mais c'est LUI qu'on a choisi de croire)."""
    assert (await fetch_version(server.port, verify_ssl=True, pinned_cert=pem(server.cert)))["version"] == "9.1"
    with pytest.raises(httpx.ConnectError):
        await fetch_version(server.port, verify_ssl=True)
