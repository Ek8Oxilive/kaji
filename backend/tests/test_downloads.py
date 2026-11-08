import re
from urllib.parse import parse_qs

import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
TOKEN_IN_URL = "jeton-secret-dans-lurl"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
UPID = "UPID:enzo:0001A2B3:00C4D5E6:67890ABC:download:debian.iso:kaji@pve!kaji:"
SHA256 = "a" * 64
CALLS: list[dict] = []
ST: dict = {}

# Paramètres que le vrai Proxmox accepte (apidoc.js du cluster réel) :
DOWNLOAD_OK = {"checksum", "checksum-algorithm", "compression", "content", "filename", "url", "verify-certificates"}
UPLOAD_FIELDS_OK = {"checksum", "checksum-algorithm", "content"}
ALGOS = {"md5", "sha1", "sha224", "sha256", "sha384", "sha512"}


def _parts(request: httpx.Request):
    """Découpe un multipart comme pveproxy : champs texte, puis la partie fichier (`name="filename"`)."""
    m = re.fullmatch(r"multipart/form-data; boundary=(\w+)", request.headers.get("content-type", ""))
    assert m, "Content-Type multipart attendu"
    raw = request.content
    assert request.headers["content-length"] == str(len(raw)), "Content-Length doit être exact"
    sep = ("--" + m.group(1)).encode()
    out = []
    for part in raw.split(sep)[1:-1]:
        head, _, data = part.partition(b"\r\n\r\n")
        out.append((head.decode(), data.removesuffix(b"\r\n")))
    assert raw.endswith(sep + b"--\r\n")
    return out


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    call = {"method": request.method, "path": p, "query": dict(request.url.params)}
    CALLS.append(call)
    if ST.get("fail"):
        return httpx.Response(403, json={"data": None, "message": SECRET})
    if (request.method, p) == ("GET", "/nodes/enzo/query-url-metadata"):
        if set(call["query"]) - {"url", "verify-certificates"} or "url" not in call["query"]:
            return httpx.Response(400, json={"data": None, "message": "paramètre refusé"})
        if "127.0.0.1" in call["query"]["url"]:
            return httpx.Response(500, json={"data": None, "message": "invalid server response"})
        return httpx.Response(200, json={"data": ST.get("meta", {"filename": "d.iso", "mimetype": "application/x-iso9660-image", "size": 42, "evil": "x"})})
    m = re.fullmatch(r"/nodes/enzo/storage/([^/]+)/(download-url|upload)", p)
    if request.method == "POST" and m and m.group(2) == "download-url":
        body = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        call["body"] = body
        bad = set(body) - DOWNLOAD_OK
        if bad or not {"url", "filename", "content"} <= set(body) or body["content"] not in ("iso", "vztmpl", "import"):
            return httpx.Response(400, json={"data": None, "message": f"paramètre refusé {sorted(bad)}"})
        if body.get("verify-certificates") not in ("0", "1") or ("checksum" in body) != ("checksum-algorithm" in body):
            return httpx.Response(400, json={"data": None, "message": "paramètres incohérents"})
        return httpx.Response(200, json={"data": UPID})
    if request.method == "POST" and m and m.group(2) == "upload":
        parts = _parts(request)
        fields = {re.search(r'name="([\w-]+)"', h).group(1): d.decode() for h, d in parts[:-1]}
        head, data = parts[-1]
        if 'name="filename"; filename="' not in head or set(fields) - UPLOAD_FIELDS_OK or "content" not in fields:
            return httpx.Response(400, json={"data": None, "message": "multipart invalide"})
        call["fields"], call["file"], call["file_head"] = fields, data, head
        return httpx.Response(200, json={"data": UPID})
    return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})


@pytest.fixture
def api(client):
    CALLS.clear()
    ST.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def base(cid, st="local"):
    return f"/api/connections/{cid}/nodes/enzo"


def dl(c, cid, storage="local", **b):
    body = {"url": "https://exemple.org/debian.iso", "filename": "debian.iso", "content": "iso", **b}
    return c.post(f"{base(cid)}/storage/{storage}/download-url", json=body)


def writes():
    return [x for x in CALLS if x["method"] != "GET"]


# ---------------------------------------------------------------- téléchargement par URL
def test_download_ok_and_exact_params(api):
    c, cid = api
    r = dl(c, cid)
    assert r.status_code == 202 and r.json() == {"upid": UPID, "node": "enzo"}
    assert writes()[0]["body"] == {"url": "https://exemple.org/debian.iso", "filename": "debian.iso", "content": "iso", "verify-certificates": "1"}


def test_download_with_checksum_and_no_cert_check(api):
    c, cid = api
    assert dl(c, cid, checksum_algorithm="sha256", checksum=SHA256.upper(), verify_certificates=False).status_code == 202
    assert writes()[0]["body"]["checksum"] == SHA256 and writes()[0]["body"]["checksum-algorithm"] == "sha256"
    assert writes()[0]["body"]["verify-certificates"] == "0"


def test_download_vztmpl_and_import(api):
    c, cid = api
    assert dl(c, cid, url="http://h.lan/t.tar.zst", filename="debian-12.tar.zst", content="vztmpl").status_code == 202
    assert dl(c, cid, url="http://h.lan/d.qcow2", filename="d.qcow2", content="import").status_code == 202


@pytest.mark.parametrize("url", [
    "ftp://exemple.org/a.iso", "file:///etc/passwd", "javascript:alert(1)", "//exemple.org/a.iso", "exemple.org/a.iso",
    "http://127.0.0.1:8006/a.iso", "http://127.1.2.3/a.iso", "http://[::1]/a.iso", "http://localhost/a.iso", "http://LOCALHOST./a.iso",
    "http://x.localhost/a.iso", "http://0.0.0.0/a.iso", "http://169.254.169.254/latest", "http://[fe80::1]/a.iso", "http://224.0.0.1/a.iso",
    "http://user:pass@exemple.org/a.iso", "https://exemple.org@evil.org/a.iso", "https://exemple.org/a b.iso", "https://exemple.org/a\n.iso",
    "https://exemple.org:abc/a.iso", "https://" + "a" * 2000, "http://",
])
def test_download_url_refused_without_any_call(api, url):
    c, cid = api
    assert dl(c, cid, url=url).status_code == 422 and not CALLS


def test_lan_urls_are_allowed(api):
    c, cid = api
    assert dl(c, cid, url="http://192.168.1.50:8080/debian.iso").status_code == 202       # un NAS du réseau local reste permis


@pytest.mark.parametrize("name,content", [
    ("debian.txt", "iso"), ("../etc.iso", "iso"), ("a/b.iso", "iso"), (".hidden.iso", "iso"), ("a b.iso", "iso"), ("a;b.iso", "iso"),
    ("a\n.iso", "iso"), ("x" * 260 + ".iso", "iso"), ("d.iso", "vztmpl"), ("d.tar.gz", "iso"), ("d.iso", "import"), ("d..iso", "iso"), ("é.iso", "iso"),
])
def test_filename_validated(api, name, content):
    c, cid = api
    assert dl(c, cid, filename=name, content=content).status_code == 422 and not CALLS


@pytest.mark.parametrize("b", [
    {"checksum_algorithm": "sha256"}, {"checksum": SHA256}, {"checksum_algorithm": "sha256", "checksum": "abc"},
    {"checksum_algorithm": "sha256", "checksum": "g" * 64}, {"checksum_algorithm": "md5", "checksum": SHA256},
    {"checksum_algorithm": "crc32", "checksum": "a" * 8}, {"content": "backup"}, {"content": "images"},
])
def test_checksum_and_content_validated(api, b):
    c, cid = api
    assert dl(c, cid, **b).status_code == 422 and not CALLS


def test_storage_and_node_validated(api):
    c, cid = api
    assert dl(c, cid, storage="a b").status_code == 422 and not CALLS
    assert c.post(f"/api/connections/{cid}/nodes/bad node/storage/local/download-url", json={}).status_code == 422


def test_audit_says_checksum_was_required_not_verified(api):
    """Le téléchargement est une tâche : au moment de l'audit, rien n'est encore vérifié (le nœud peut refuser la somme)."""
    c, cid = api
    dl(c, cid, checksum_algorithm="sha256", checksum=SHA256)
    up(c, cid, checksum_algorithm="sha256", checksum=SHA256)
    log = c.get("/api/audit").text
    assert log.count("sha256 exigé") == 2 and "vérifié" not in log


def test_url_not_logged_in_full(api):
    c, cid = api
    dl(c, cid, url=f"https://exemple.org/d.iso?token={TOKEN_IN_URL}")
    log = c.get("/api/audit")
    assert log.status_code == 200 and TOKEN_IN_URL not in log.text and "exemple.org" in log.text and "storage-download" in log.text


# ---------------------------------------------------------------- métadonnées
def test_metadata_whitelisted(api):
    c, cid = api
    r = c.get(f"{base(cid)}/url-metadata", params={"url": "https://exemple.org/d.iso"})
    assert r.status_code == 200 and r.json() == {"filename": "d.iso", "mimetype": "application/x-iso9660-image", "size": 42}
    assert CALLS[0]["query"] == {"url": "https://exemple.org/d.iso", "verify-certificates": "1"}


def test_metadata_certificate_flag_is_forwarded(api):
    c, cid = api
    assert c.get(f"{base(cid)}/url-metadata", params={"url": "https://exemple.org/d.iso", "verify_certificates": "false"}).status_code == 200
    assert CALLS[0]["query"]["verify-certificates"] == "0"


def test_metadata_refuses_local_urls_and_junk(api):
    c, cid = api
    assert c.get(f"{base(cid)}/url-metadata", params={"url": "http://127.0.0.1:8006/"}).status_code == 422 and not CALLS
    ST["meta"] = {"filename": 5, "mimetype": ["x"], "size": -3}
    assert c.get(f"{base(cid)}/url-metadata", params={"url": "https://exemple.org/d.iso"}).json() == {"filename": None, "mimetype": None, "size": None}


# ---------------------------------------------------------------- téléversement
def up(c, cid, data=b"contenu-de-l-iso", storage="local", **q):
    q = {"filename": "debian.iso", "content": "iso", **q}
    return c.post(f"{base(cid)}/storage/{storage}/upload", params=q, content=data)


def test_upload_streams_multipart_exactly(api):
    c, cid = api
    data = bytes(range(256)) * 50 + b"\r\n--fin\r\n"             # contient des octets quelconques, y compris des CRLF et un faux délimiteur
    r = up(c, cid, data)
    assert r.status_code == 202 and r.json() == {"upid": UPID, "node": "enzo"}
    w = writes()[0]
    assert w["file"] == data and w["fields"] == {"content": "iso"} and 'filename="debian.iso"' in w["file_head"]


def test_upload_with_checksum(api):
    c, cid = api
    assert up(c, cid, checksum_algorithm="sha256", checksum=SHA256).status_code == 202
    assert writes()[0]["fields"] == {"content": "iso", "checksum-algorithm": "sha256", "checksum": SHA256}


def test_upload_requires_known_size(api):
    c, cid = api
    r = c.post(f"{base(cid)}/storage/local/upload", params={"filename": "d.iso", "content": "iso"}, content=iter([b"a", b"b"]))
    assert r.status_code == 411 and not CALLS
    assert up(c, cid, b"").status_code == 411 and not CALLS


def test_upload_too_big_refused_before_any_call(api):
    c, cid = api
    r = c.post(f"{base(cid)}/storage/local/upload", params={"filename": "d.iso", "content": "iso"}, content=b"x",
               headers={"Content-Length": str(20 * 1024**3 + 1)})
    assert r.status_code == 413 and not CALLS


def test_upload_body_larger_than_announced_is_refused(api):
    c, cid = api
    r = c.post(f"{base(cid)}/storage/local/upload", params={"filename": "d.iso", "content": "iso"}, content=b"x" * 50,
               headers={"Content-Length": "5"})
    assert r.status_code == 400 and not writes()
    assert ("storage-upload", "error") in [(i["action"], i["status"]) for i in c.get("/api/audit").json()]


@pytest.mark.parametrize("q", [
    {"filename": "d.txt"}, {"filename": "../d.iso"}, {"filename": "a b.iso"}, {"content": "backup"}, {"content": "iso", "filename": "d.tar.gz"},
    {"checksum_algorithm": "sha256"}, {"checksum_algorithm": "sha256", "checksum": "zz"},
])
def test_upload_validated_without_call(api, q):
    c, cid = api
    assert up(c, cid, **q).status_code == 422 and not CALLS


def test_filename_with_quote_cannot_break_multipart(api):
    c, cid = api
    assert up(c, cid, filename='a"b.iso').status_code == 422 and not CALLS


# ---------------------------------------------------------------- audit, fuites, accès
def test_audit_and_no_leak_on_proxmox_error(api):
    c, cid = api
    up(c, cid)
    dl(c, cid, filename="mauvais.txt")                   # refus
    ST["fail"] = True
    r = up(c, cid)
    assert r.status_code == 502 and SECRET not in r.text
    log = c.get("/api/audit")
    acts = [(i["action"], i["status"]) for i in log.json()]
    for a in (("storage-upload", "started"), ("storage-download", "error"), ("storage-upload", "error")):
        assert a in acts
    assert SECRET not in log.text


def test_requires_login(client):
    for method, path in (("get", "/url-metadata?url=https://a.org/x.iso"), ("post", "/storage/local/upload"), ("post", "/storage/local/download-url")):
        assert getattr(client, method)(f"/api/connections/1/nodes/enzo{path}").status_code == 401
