from datetime import datetime, timedelta, timezone

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

from app import certspec as C
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
CALLS: list[tuple[str, str, str]] = []
ST: dict = {}


def make(cn="enzo.lab.fr", issuer_key=None, issuer_cn=None, days=90, start=-1, key=None, san=("enzo.lab.fr",), encrypt=False):
    key = key or ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(timezone.utc)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer_cn or cn)])
    b = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(key.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(now + timedelta(days=start)).not_valid_after(now + timedelta(days=start + days)))
    if san:
        b = b.add_extension(x509.SubjectAlternativeName([x509.DNSName(s) for s in san]), critical=False)
    cert = b.sign(issuer_key or key, hashes.SHA256())
    enc = serialization.BestAvailableEncryption(b"mdp") if encrypt else serialization.NoEncryption()
    return (cert.public_bytes(serialization.Encoding.PEM).decode(),
            key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, enc).decode())


CA_KEY = ec.generate_private_key(ec.SECP256R1())
LEAF, LEAF_KEY = make(issuer_key=CA_KEY, issuer_cn="Mon CA")                    # signé par une CA : pas auto-signé
CA_PEM, _ = make(cn="Mon CA", key=CA_KEY, san=())
SELF, SELF_KEY = make()                                                          # auto-signé


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    CALLS.append((request.method, p, request.content.decode() + request.url.query.decode()))
    if ST.get("fail"):
        return httpx.Response(ST["fail"], json={"data": None, "message": SECRET})
    if request.method == "GET" and p.endswith("/certificates/info"):
        if ST.get("info_down"):
            return httpx.Response(500, json={"data": None})
        files = [{"filename": "pve-ssl.pem"}] + ([{"filename": "pveproxy-ssl.pem"}] if ST.get("has_custom") else [])
        return httpx.Response(200, json={"data": files})
    return httpx.Response(200, json={"data": {"filename": "pveproxy-ssl.pem"}})


@pytest.fixture
def api(client):
    CALLS.clear()
    ST.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def put(c, cid, certs=LEAF + CA_PEM, key=LEAF_KEY, **b):
    return c.put(f"/api/connections/{cid}/nodes/enzo/certificates/custom", json={"certificates": certs, "key": key, "confirm": True, **b})


def writes():
    return [x for x in CALLS if x[0] != "GET"]


def test_install_sends_chain_key_and_flags(api):
    c, cid = api
    r = put(c, cid)
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["self_signed"] is False and r.json()["chain_length"] == 2
    m, p, body = writes()[0]
    assert (m, p) == ("POST", "/nodes/enzo/certificates/custom") and "force=0" in body and "restart=1" in body and "BEGIN" in httpx.QueryParams(body)["certificates"]


def test_key_never_leaks_anywhere(api):
    c, cid = api
    needle = LEAF_KEY.splitlines()[1]
    r1 = put(c, cid)
    r2 = put(c, cid, key=SELF_KEY)                                         # clé qui ne correspond pas : erreur
    r3 = c.post(f"/api/connections/{cid}/nodes/enzo/certificates/custom/check", json={"certificates": LEAF, "key": LEAF_KEY})
    ST["fail"] = 403
    r4 = put(c, cid, replace_existing=True)
    for r in (r1, r2, r3, r4):
        assert needle not in r.text and "PRIVATE KEY" not in r.text
    assert needle not in c.get("/api/audit").text and "PRIVATE KEY" not in c.get("/api/audit").text and SECRET not in c.get("/api/audit").text


def test_invalid_body_error_does_not_echo_key(api):
    c, cid = api
    r = c.put(f"/api/connections/{cid}/nodes/enzo/certificates/custom", json={"certificates": "x" * 40000, "key": LEAF_KEY, "confirm": True})
    assert r.status_code == 422 and LEAF_KEY.splitlines()[1] not in r.text and not writes()
    assert "Fournis" not in r.text                         # refusé par la limite de taille, avant toute analyse du contenu


def test_needs_confirm(api):
    c, cid = api
    assert put(c, cid, confirm=False).status_code == 400 and not writes()


@pytest.mark.parametrize("why,certs,key", [
    ("mauvaise clé", LEAF, SELF_KEY),
    ("clé dans le champ certificats", LEAF + LEAF_KEY, LEAF_KEY),
    ("texte parasite", "bonjour\n" + LEAF, LEAF_KEY),
    ("aucun certificat", "", LEAF_KEY),
    ("certificat illisible", "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n", LEAF_KEY),
    ("clé illisible", LEAF, "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n"),
    ("pas de clé", LEAF, "rien"),
    ("expiré", make(days=10, start=-30)[0], make(days=10, start=-30)[1]),
    ("pas encore valide", None, None),
    ("trop de certificats", LEAF * 7, LEAF_KEY),
])
def test_bad_material_refused(api, why, certs, key):
    c, cid = api
    if why == "pas encore valide":
        certs, key = make(start=5)
    if why == "expiré":
        certs, key = make(days=10, start=-30)
    assert put(c, cid, certs=certs, key=key).status_code == 422, why
    assert not writes()


def test_encrypted_and_weak_keys_refused(api):
    c, cid = api
    certs, key = make(encrypt=True)
    assert put(c, cid, certs=certs, key=key).status_code == 422
    weak = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    certs, key = make(key=weak)
    r = put(c, cid, certs=certs, key=key)
    assert r.status_code == 422 and "courte" in r.json()["detail"]
    assert not writes()


def test_existing_custom_needs_explicit_replace(api):
    c, cid = api
    ST["has_custom"] = True
    assert put(c, cid).status_code == 409 and not writes()
    assert put(c, cid, replace_existing=True).status_code == 200
    assert "force=1" in writes()[0][2]


def test_unreadable_certificate_state_refuses(api):
    c, cid = api
    ST["info_down"] = True
    assert put(c, cid).status_code == 502 and not writes()


def test_self_signed_refused_when_connection_verifies_tls(api):
    c, cid = api
    assert put(c, cid, certs=SELF, key=SELF_KEY).status_code == 200                       # verify_ssl faux : permis
    CALLS.clear()
    c.patch(f"/api/connections/{cid}", json={"verify_ssl": True})
    r = put(c, cid, certs=SELF, key=SELF_KEY)
    assert r.status_code == 422 and "perdrait" in r.json()["detail"] and not writes()
    assert put(c, cid).status_code == 200                                                  # signé par une CA : permis


def test_check_is_local_and_returns_summary(api):
    c, cid = api
    r = c.post(f"/api/connections/{cid}/nodes/enzo/certificates/custom/check", json={"certificates": LEAF + CA_PEM, "key": LEAF_KEY})
    d = r.json()
    assert r.status_code == 200 and d["subject"] == "enzo.lab.fr" and d["issuer"] == "Mon CA" and d["san"] == ["enzo.lab.fr"] and d["key"].startswith("EC")
    assert len(d["fingerprint"].split(":")) == 32 and not CALLS
    assert c.post(f"/api/connections/{cid}/nodes/enzo/certificates/custom/check", json={"certificates": LEAF, "key": SELF_KEY}).status_code == 422


def test_remove_custom(api):
    c, cid = api
    url = f"/api/connections/{cid}/nodes/enzo/certificates/custom"
    assert c.delete(url).status_code == 400                                              # sans confirmation
    assert c.delete(url + "?confirm=true").status_code == 409                            # aucun certificat personnalisé
    ST["has_custom"] = True
    assert c.delete(url + "?confirm=true&restart=false").status_code == 200
    assert writes() == [("DELETE", "/nodes/enzo/certificates/custom", "restart=0")]


def test_remove_refused_when_connection_verifies_tls(api):
    c, cid = api
    ST["has_custom"] = True
    c.patch(f"/api/connections/{cid}", json={"verify_ssl": True})
    assert c.delete(f"/api/connections/{cid}/nodes/enzo/certificates/custom?confirm=true").status_code == 422 and not writes()


def test_requires_login_and_node_validated(api):
    c, cid = api
    CALLS.clear()
    r = c.put(f"/api/connections/{cid}/nodes/a;b/certificates/custom", json={"certificates": LEAF, "key": LEAF_KEY, "confirm": True})
    assert r.status_code in (404, 422) and not CALLS
    c.post("/api/auth/logout")
    assert put(c, cid).status_code == 401 and c.delete(f"/api/connections/{cid}/nodes/enzo/certificates/custom?confirm=true").status_code == 401


def test_audit_success_refusal_error(api):
    c, cid = api
    put(c, cid)
    put(c, cid, confirm=False)
    ST["fail"] = 403
    assert put(c, cid, replace_existing=True).status_code == 502
    log = c.get("/api/audit").json()[::-1]
    assert [(e["action"], e["status"]) for e in log] == [("node-cert-install", "ok"), ("node-cert-install", "error"), ("node-cert-install", "error")]
    assert "empreinte" in log[0]["detail"]


def test_analyse_summary_unit():
    d = C.analyse(SELF, SELF_KEY)
    assert d["self_signed"] is True and d["chain_length"] == 1
