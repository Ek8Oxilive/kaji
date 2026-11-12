import httpx
import pytest

from app import nodeconf as N
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
DIGEST = "a" * 40
HOSTS = "127.0.0.1 localhost.localdomain localhost\n192.168.1.200 enzo.lab.fr enzo\n\n::1 ip6-localhost ip6-loopback\n"
CALLS: list[tuple[str, str, str]] = []
ST: dict = {}


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    CALLS.append((request.method, p, request.content.decode()))
    if ST.get("fail"):
        return httpx.Response(ST["fail"], json={"data": None, "message": SECRET})
    if request.method == "GET" and p.endswith("/hosts"):
        return httpx.Response(200, json={"data": {"data": HOSTS, "digest": ST.get("digest", DIGEST)}})
    if request.method == "POST" and p.endswith("/hosts") and ST.get("race"):
        # le vrai Proxmox met son message dans la phrase de raison HTTP (c'est ce que Kaji relit)
        return httpx.Response(500, json={"data": None}, extensions={"reason_phrase": b"detected modified configuration - file changed by other user? Try again."})
    return httpx.Response(200, json={"data": None})


@pytest.fixture
def api(client):
    CALLS.clear()
    ST.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def u(cid, what, node="enzo"):
    return f"/api/connections/{cid}/nodes/{node}/{what}"


def writes():
    return [x for x in CALLS if x[0] != "GET"]


# ---------------------------------------------------------------- DNS
def test_dns_written_with_constant_fields(api):
    c, cid = api
    r = c.put(u(cid, "dns"), json={"search": "lab.fr", "servers": ["1.1.1.1", "2606:4700::1111"], "confirm": True, "extra": "x"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert writes() == [("PUT", "/nodes/enzo/dns", "search=lab.fr&dns1=1.1.1.1&dns2=2606%3A4700%3A%3A1111")]


def test_dns_needs_confirm(api):
    c, cid = api
    assert c.put(u(cid, "dns"), json={"search": "lab.fr", "servers": ["1.1.1.1"]}).status_code == 400
    assert not writes()


@pytest.mark.parametrize("body", [
    {"search": "lab.fr", "servers": []}, {"search": "lab.fr", "servers": ["a;b"]}, {"search": "lab.fr", "servers": ["1.1.1.1", "1.1.1.1"]},
    {"search": "lab.fr", "servers": ["1.1.1.1"] * 4}, {"search": "lab fr", "servers": ["1.1.1.1"]}, {"search": "-lab.fr", "servers": ["1.1.1.1"]},
    {"search": "lab.fr\nnameserver 6.6.6.6", "servers": ["1.1.1.1"]}, {"search": "", "servers": ["1.1.1.1"]}, {"search": "lab.fr", "servers": ["1.1.1.256"]},
    {"search": "lab.fr", "servers": ["1.1.1.1\n"]}, {"search": "a" * 254, "servers": ["1.1.1.1"]},
])
def test_dns_validated(api, body):
    c, cid = api
    assert c.put(u(cid, "dns"), json={**body, "confirm": True}).status_code == 422
    assert not CALLS


# ---------------------------------------------------------------- hosts
def test_hosts_read(api):
    c, cid = api
    assert c.get(u(cid, "hosts")).json() == {"content": HOSTS, "digest": DIGEST}


def test_hosts_written_with_digest(api):
    c, cid = api
    new = HOSTS + "192.168.1.201 enzo2.lab.fr enzo2\n"
    assert c.put(u(cid, "hosts"), json={"content": new, "digest": DIGEST, "confirm": True}).status_code == 200
    m, p, body = writes()[0]
    assert (m, p) == ("POST", "/nodes/enzo/hosts") and "digest=" + DIGEST in body and "enzo2.lab.fr" in body


def test_hosts_needs_confirm_and_digest(api):
    c, cid = api
    assert c.put(u(cid, "hosts"), json={"content": HOSTS, "digest": DIGEST}).status_code == 400
    for digest in (None, "", "zz" * 20, "a" * 39, "A" * 40, "a" * 41, "x" + "a" * 40, "a" * 40 + "\n", "a" * 40 + ";rm"):
        assert c.put(u(cid, "hosts"), json={"content": HOSTS, "digest": digest, "confirm": True}).status_code == 422
    assert not writes()


@pytest.mark.parametrize("content,why", [
    ("192.168.1.200 enzo.lab.fr enzo\n", "localhost"),                                                    # plus de localhost
    ("127.0.0.1 localhost\n", "nœud"),                                                                     # plus de ligne pour le nœud
    ("127.0.0.1 localhost enzo\n", "nœud"),                                                                # nœud sur la boucle locale : cassé
    ("127.0.0.1 localhost\n192.168.1.200 autre\n", "nœud"),
    ("127.0.0.1 localhost\n192.168.1.200 enzo\nnimportequoi\n", "adresse"),
    ("127.0.0.1 localhost\n192.168.1.200 enzo\n999.1.1.1 x\n", "adresse"),
    ("127.0.0.1 localhost\n192.168.1.200 enzo ;rm\n", "Nom"),
    ("127.0.0.1 localhost\r\n192.168.1.200 enzo\r\n", "interdits"),
    ("127.0.0.1 localhost\n192.168.1.200 enzo\x00\n", "interdits"),
])
def test_hosts_content_guards(api, content, why):
    c, cid = api
    r = c.put(u(cid, "hosts"), json={"content": content, "digest": DIGEST, "confirm": True})
    assert r.status_code == 422 and not writes()
    assert "127.0.0.1" not in r.json()["detail"] and "999.1.1.1" not in r.json()["detail"]        # jamais le contenu dans l'erreur


def test_hosts_too_big(api):
    c, cid = api
    assert c.put(u(cid, "hosts"), json={"content": HOSTS + "# " + "x" * 9000, "digest": DIGEST, "confirm": True}).status_code == 422
    assert not writes()


def test_hosts_accepts_comments_and_fqdn_node(api):
    c, cid = api
    ok = "# commentaire\n127.0.0.1 localhost # boucle\n10.0.0.9 enzo.lab.fr\n"
    assert c.put(u(cid, "hosts"), json={"content": ok, "digest": DIGEST, "confirm": True}).status_code == 200


# ---------------------------------------------------------------- fuseau horaire
def test_timezone(api):
    c, cid = api
    assert c.put(u(cid, "time"), json={"timezone": "Europe/Paris"}).status_code == 200
    assert writes() == [("PUT", "/nodes/enzo/time", "timezone=Europe%2FParis")]


@pytest.mark.parametrize("tz", ["", "../etc/passwd", "Europe/Paris;rm", "Europe//Paris", "/Europe", "Europe/Paris\n", "a/b/c/d", "1Europe", "x" * 120])
def test_timezone_validated(api, tz):
    c, cid = api
    assert c.put(u(cid, "time"), json={"timezone": tz}).status_code == 422
    assert not CALLS


# ---------------------------------------------------------------- transverse
def test_requires_login_and_node_validated(api):
    c, cid = api
    assert c.put(u(cid, "time", node="a;b"), json={"timezone": "UTC"}).status_code == 422
    c.post("/api/auth/logout")
    assert c.put(u(cid, "time"), json={"timezone": "UTC"}).status_code == 401 and c.get(u(cid, "hosts")).status_code == 401
    assert not CALLS


def test_audit_and_no_secret_or_content(api):
    c, cid = api
    c.put(u(cid, "time"), json={"timezone": "UTC"})
    c.put(u(cid, "dns"), json={"search": "lab.fr", "servers": ["1.1.1.1"]})                       # refusé : pas de confirmation
    ST["fail"] = 403
    assert c.put(u(cid, "hosts"), json={"content": HOSTS, "digest": DIGEST, "confirm": True}).status_code == 502
    log = c.get("/api/audit").json()[::-1]
    assert [(e["action"], e["status"]) for e in log] == [("node-timezone", "ok"), ("node-dns", "error"), ("node-hosts", "error")]
    text = c.get("/api/audit").text
    assert SECRET not in text and "192.168.1.200" not in text


def test_hosts_stale_digest_is_409_without_write(api):
    c, cid = api
    ST["digest"] = "b" * 40                                    # le fichier a changé depuis la lecture de l'utilisateur
    r = c.put(u(cid, "hosts"), json={"content": HOSTS, "digest": DIGEST, "confirm": True})
    assert r.status_code == 409 and "digest périmé" in r.json()["detail"]
    assert not writes()
    assert [(e["action"], e["status"]) for e in c.get("/api/audit").json()] == [("node-hosts", "error")]


def test_hosts_unreadable_digest_leaves_decision_to_proxmox(api):
    c, cid = api
    ST["digest"] = "illisible"                                 # relecture sans digest valide : pas de faux 409
    assert c.put(u(cid, "hosts"), json={"content": HOSTS, "digest": DIGEST, "confirm": True}).status_code == 200
    assert len(writes()) == 1


def test_hosts_race_reported_by_proxmox_is_409(api):
    c, cid = api
    ST["race"] = True                                          # modifié entre notre relecture et l'écriture
    r = c.put(u(cid, "hosts"), json={"content": HOSTS, "digest": DIGEST, "confirm": True})
    assert r.status_code == 409 and "digest périmé" in r.json()["detail"] and "Try again" not in r.text
    assert len(writes()) == 1


def test_hosts_digest_checked_only_after_other_guards(api):
    c, cid = api
    ST["digest"] = "b" * 40
    assert c.put(u(cid, "hosts"), json={"content": HOSTS, "digest": DIGEST}).status_code == 400            # pas de confirmation
    assert c.put(u(cid, "hosts"), json={"content": "127.0.0.1 localhost\n", "digest": DIGEST, "confirm": True}).status_code == 422
    assert not CALLS                                           # aucune lecture inutile quand une garde refuse déjà


def test_hosts_problem_unit():
    assert N.hosts_problem(HOSTS, "enzo") is None
    assert N.hosts_problem(HOSTS, "enzo2") is not None
