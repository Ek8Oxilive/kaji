import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
CALLS: list[tuple[str, str, str]] = []
ST: dict = {}

GOOD = {"name": "depot-perso", "types": ["deb"], "uris": ["https://apt.example.org/debian"], "suites": ["trixie"], "components": ["main"],
        "signed_by": "/usr/share/keyrings/example.gpg"}


def _payload():
    files = [{"path": "/etc/apt/sources.list.d/debian.sources", "digest": [1], "repositories": [
        {"Types": ["deb"], "URIs": ["http://deb.debian.org/debian/"], "Suites": ["trixie"], "Components": ["main"], "Enabled": 1}]}]
    if ST.get("exists"):
        files.append({"path": "/etc/apt/sources.list.d/depot-perso.sources", "digest": [2], "repositories": [
            {"Types": ["deb"], "URIs": ["https://apt.example.org/debian"], "Suites": ["trixie"], "Components": ["main"], "Enabled": 1}]})
    return {"digest": "ab" * 32, "errors": [], "infos": [], "files": files, "standard-repos": []}


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    CALLS.append((request.method, p, request.content.decode()))
    if request.method == "GET" and p.endswith("/apt/repositories"):
        return httpx.Response(500, json={"data": None}) if ST.get("read_down") else httpx.Response(200, json={"data": _payload()})
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


def url(cid, node="enzo"):
    return f"/api/connections/{cid}/nodes/{node}/apt/repositories/custom"


def test_generates_file_and_commands_without_any_write(api):
    c, cid = api
    r = c.post(url(cid), json=GOOD)
    assert r.status_code == 200
    d = r.json()
    assert d["file"] == "/etc/apt/sources.list.d/depot-perso.sources" and d["exists"] is False
    assert d["content"] == ("Types: deb\nURIs: https://apt.example.org/debian\nSuites: trixie\nComponents: main\n"
                            "Signed-By: /usr/share/keyrings/example.gpg\n")
    assert d["commands"] == ["cat > /etc/apt/sources.list.d/depot-perso.sources <<'KAJI_EOF'\n" + d["content"] + "KAJI_EOF", "apt update"]
    assert all(m == "GET" for m, _, _ in CALLS)                      # lecture seule : Kaji n'écrit jamais chez Proxmox
    assert not any("sources.list.d/depot-perso" in b for _, _, b in CALLS)


def test_all_fields_in_fixed_order(api):
    c, cid = api
    d = c.post(url(cid), json={**GOOD, "types": ["deb", "deb-src"], "uris": ["https://a.example.org/x", "http://b.example.org:8080/y"],
                               "suites": ["trixie", "trixie-updates"], "components": ["main", "contrib"], "architectures": ["amd64", "arm64"]}).json()
    assert d["content"] == ("Types: deb deb-src\nURIs: https://a.example.org/x http://b.example.org:8080/y\nSuites: trixie trixie-updates\n"
                            "Components: main contrib\nArchitectures: amd64 arm64\nSigned-By: /usr/share/keyrings/example.gpg\n")


def test_existing_file_is_flagged_first(api):
    c, cid = api
    ST["exists"] = True
    d = c.post(url(cid), json=GOOD).json()
    assert d["exists"] is True and d["warnings"][0].startswith("un fichier de ce nom existe déjà")


def test_unreadable_repositories_do_not_block(api):
    c, cid = api
    ST["read_down"] = True
    r = c.post(url(cid), json=GOOD)
    assert r.status_code == 200 and r.json()["exists"] is None and r.json()["content"]


def test_warnings(api):
    c, cid = api
    w = c.post(url(cid), json={**GOOD, "uris": ["http://apt.example.org/debian"], "signed_by": None}).json()["warnings"]
    assert any("http (non chiffrée)" in x for x in w) and any("sans « Signed-By »" in x for x in w)
    w = c.post(url(cid), json={**GOOD, "uris": ["https://download.proxmox.com/debian/pve"], "components": ["pve-test"]}).json()["warnings"]
    assert any("Ajouter un dépôt standard" in x for x in w) and any("composant de test" in x for x in w)
    w = c.post(url(cid), json=GOOD).json()["warnings"]
    assert w == ["la clé indiquée doit déjà exister sur le nœud (Kaji ne la télécharge pas)"]


@pytest.mark.parametrize("patch", [
    {"name": ""}, {"name": "A"}, {"name": "a;b"}, {"name": "a b"}, {"name": "-a"}, {"name": "a" * 61}, {"name": "../x"}, {"name": "a\nb"},
    {"types": []}, {"types": ["rpm"]}, {"types": ["deb", "deb"]},
    {"uris": []}, {"uris": ["ftp://a.example.org/x"]}, {"uris": ["https://user:pass@a.example.org/x"]}, {"uris": ["https://a.example.org/x?k=1"]},
    {"uris": ["https://a.example.org/x#f"]}, {"uris": ["https://a.example.org/x y"]}, {"uris": ["https://a.example.org/x\nTypes: deb"]},
    {"uris": ["https://a.example.org/../etc"]}, {"uris": ["https://a.example.org//x"]}, {"uris": ["https://a.example.org:99999/x"]},
    {"uris": ["https://a.example.org:0/x"]}, {"uris": ["file:///etc"]}, {"uris": ["https://a.example.org/x"] * 2}, {"uris": ["https://a.example.org/x"] * 4},
    {"suites": []}, {"suites": ["tri xie"]}, {"suites": ["trixie\nTypes: deb"]}, {"suites": ["../x"]}, {"suites": ["a/b/c"]}, {"suites": ["t"] * 6},
    {"components": []}, {"components": ["Main"]}, {"components": ["ma in"]}, {"components": ["main\nSigned-By: /tmp/x"]}, {"components": ["_x"]},
    {"signed_by": "/tmp/key.gpg"}, {"signed_by": "/usr/share/keyrings/../../etc/x.gpg"}, {"signed_by": "/etc/apt/trusted.gpg"},
    {"signed_by": "/usr/share/keyrings/k.txt"}, {"signed_by": "/usr/share/keyrings/sub/k.gpg"}, {"signed_by": "/usr/share/keyrings/k.gpg\nTypes: deb"},
    {"signed_by": "-----BEGIN PGP PUBLIC KEY BLOCK-----"}, {"architectures": ["mips"]}, {"architectures": ["amd64", "amd64"]},
])
def test_validation_refuses_without_any_call(api, patch):
    c, cid = api
    assert c.post(url(cid), json={**GOOD, **patch}).status_code == 422
    assert not CALLS


@pytest.mark.parametrize("missing", ["name", "types", "uris", "suites", "components"])
def test_required_fields(api, missing):
    c, cid = api
    body = {k: v for k, v in GOOD.items() if k != missing}
    assert c.post(url(cid), json=body).status_code == 422 and not CALLS


def test_no_line_can_close_the_heredoc_early(api):
    c, cid = api
    d = c.post(url(cid), json={**GOOD, "signed_by": "/usr/share/keyrings/KAJI_EOF.gpg"}).json()
    lines = d["commands"][0].split("\n")
    assert lines.count("KAJI_EOF") == 1 and lines[-1] == "KAJI_EOF"


def test_requires_login_and_node_validated(api):
    c, cid = api
    assert c.post(url(cid, node="a;b"), json=GOOD).status_code == 422
    c.post("/api/auth/logout")
    assert c.post(url(cid), json=GOOD).status_code == 401
    assert not CALLS


def test_no_secret_in_answer(api):
    c, cid = api
    assert SECRET not in c.post(url(cid), json=GOOD).text
