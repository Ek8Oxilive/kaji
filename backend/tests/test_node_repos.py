import httpx
import pytest

from app import repospec as R
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient
from app.systemspec import shape_repositories

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
DIGEST = "ab" * 32
CALLS: list[tuple[str, str, str]] = []
ST: dict = {}


def repo(uri, en=1, comp="main"):
    return {"Types": ["deb"], "URIs": [uri], "Suites": ["trixie"], "Components": [comp], "Enabled": en, "FileType": "sources"}


def repos_payload():
    return {"digest": ST.get("digest", DIGEST), "errors": [], "infos": [], "files": [
        {"path": "/etc/apt/sources.list", "file-type": "list", "digest": [1, 2], "repositories": [repo("http://download.proxmox.com/debian/pve", 1, "pve-no-subscription")]},
        {"path": "/etc/apt/sources.list.d/ceph.sources", "digest": [3], "repositories": [repo("https://enterprise.proxmox.com/debian/ceph-squid", 0, "enterprise"), repo("http://download.proxmox.com/debian/ceph-squid", 1, "no-subscription")]},
        {"path": "/etc/apt/sources.list.d/debian.sources", "digest": [4], "repositories": [repo("http://deb.debian.org/debian/"), repo("http://security.debian.org/debian-security/")]},
        {"path": "/etc/apt/sources.list.d/pve-enterprise.sources", "digest": [5], "repositories": [{"Types": ["deb"], "URIs": ["https://enterprise.proxmox.com/debian/pve"], "Suites": ["trixie"], "Components": ["pve-enterprise"], "Enabled": 0}]},
    ], "standard-repos": ST.get("standard", [
        {"handle": "enterprise", "name": "Enterprise", "description": "d"}, {"handle": "no-subscription", "name": "No-Subscription", "status": 1},
        {"handle": "test", "name": "Test", "description": "t"}, {"handle": "ceph-squid-enterprise", "name": "Ceph", "status": 0}])}


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    CALLS.append((request.method, p, request.content.decode()))
    if request.method == "GET" and p.endswith("/apt/repositories"):
        return httpx.Response(500, json={"data": None}) if ST.get("read_down") else httpx.Response(200, json={"data": repos_payload()})
    if request.method == "GET" and p.endswith("/subscription"):
        return httpx.Response(200, json={"data": {"status": ST.get("sub", "notfound")}})
    if ST.get("write_fail"):
        return httpx.Response(403, json={"data": None, "message": SECRET})
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


U = "/api/connections/{}/nodes/enzo/apt/repositories"
CEPH = "/etc/apt/sources.list.d/ceph.sources"
DEB = "/etc/apt/sources.list.d/debian.sources"
PVE = "/etc/apt/sources.list"


def toggle(c, cid, path, index, enabled, **b):
    return c.put(U.format(cid), json={"path": path, "index": index, "enabled": enabled, "digest": DIGEST, "confirm": True, **b})


def add(c, cid, handle, **b):
    return c.post(U.format(cid), json={"handle": handle, "digest": DIGEST, "confirm": True, **b})


def writes():
    return [x for x in CALLS if x[0] in ("PUT", "POST")]


# ---------------------------------------------------------------- lecture
def test_read_shape_has_index_digest_and_handles():
    d = shape_repositories(repos_payload())
    assert d["digest"] == DIGEST and [r["index"] for r in d["files"][1]["repositories"]] == [0, 1]
    assert [s["handle"] for s in d["standard"]] == ["enterprise", "no-subscription", "test", "ceph-squid-enterprise"]
    assert [s["status"] for s in d["standard"]] == [None, 1, None, 0]


def test_index_is_position_in_proxmox_list_even_with_junk():
    raw = repos_payload()
    raw["files"][1]["repositories"].insert(0, "illisible")
    idx = [r["index"] for r in shape_repositories(raw)["files"][1]["repositories"]]
    assert idx == [1, 2]


@pytest.mark.parametrize("d", [None, "", "zz" * 32, "AB" * 32, "ab" * 31, ["a"], 5])
def test_unreadable_or_odd_digest_is_none(d):
    raw = repos_payload()
    raw["digest"] = d
    assert shape_repositories(raw)["digest"] is None


# ---------------------------------------------------------------- activer / désactiver
def test_enable_disabled_repo_without_risk(api):
    c, cid = api
    ST["sub"] = "active"
    assert toggle(c, cid, CEPH, 0, True).status_code == 200                          # enterprise AVEC abonnement
    assert writes() == [("PUT", "/nodes/enzo/apt/repositories", f"path=%2Fetc%2Fapt%2Fsources.list.d%2Fceph.sources&index=0&enabled=1&digest={DIGEST}")]


def test_disable_non_last_repo(api):
    c, cid = api
    assert toggle(c, cid, DEB, 1, False).status_code == 200                           # il reste un dépôt Debian
    assert "enabled=0" in writes()[0][2]


def test_enterprise_without_subscription_needs_accept_risk(api):
    c, cid = api
    r = toggle(c, cid, CEPH, 0, True)
    assert r.status_code == 409 and "enterprise" in r.json()["detail"] and not writes()
    assert toggle(c, cid, CEPH, 0, True, accept_risk=True).status_code == 200


def test_unreadable_subscription_counts_as_no_subscription(api):
    c, cid = api
    ST["sub"] = "active"
    orig = _handler

    def handler(request):
        if request.url.path.endswith("/subscription"):
            return httpx.Response(500, json={"data": None})
        return orig(request)
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(handler)))
    assert toggle(c, cid, CEPH, 0, True).status_code == 409


def test_last_proxmox_or_debian_repo_cannot_be_disabled_silently(api):
    c, cid = api
    r = toggle(c, cid, PVE, 0, False)                                                  # download.proxmox.com : il reste celui de ceph → permis
    assert r.status_code == 200
    CALLS.clear()
    assert toggle(c, cid, DEB, 0, False).status_code == 200                           # il reste security.debian.org
    # dernier dépôt Debian : on simule en ne gardant qu'un seul dépôt Debian actif
    raw = repos_payload()
    raw["files"][2]["repositories"][1]["Enabled"] = 0
    files = shape_repositories(raw)["files"]
    assert R.risks_toggle(files, DEB, 0, False, True) and "Debian" in R.risks_toggle(files, DEB, 0, False, True)[0]
    raw["files"][1]["repositories"][1]["Enabled"] = 0
    files = shape_repositories(raw)["files"]
    assert R.risks_toggle(files, PVE, 0, False, True) and "Proxmox" in R.risks_toggle(files, PVE, 0, False, True)[0]


def test_toggle_unknown_or_same_state(api):
    c, cid = api
    assert toggle(c, cid, "/etc/apt/autre.list", 0, False).status_code == 404
    assert toggle(c, cid, CEPH, 9, False).status_code == 404
    assert toggle(c, cid, CEPH, 1, True).status_code == 409                          # déjà actif
    assert not writes()


@pytest.mark.parametrize("path", ["/etc/passwd", "/etc/apt/../passwd", "etc/apt/x", "/etc/apt/", "/etc/apt/a b", "/etc/apt/x;y", "/etc/apt/x\n"])
def test_path_validated(api, path):
    c, cid = api
    assert toggle(c, cid, path, 0, False).status_code == 422 and not CALLS


@pytest.mark.parametrize("digest", [None, "", "zz" * 32, "ab" * 31, "AB" * 32, "ab" * 33, "ab" * 32 + "\n", "x" + "ab" * 32])
def test_digest_validated(api, digest):
    c, cid = api
    r = c.put(U.format(cid), json={"path": CEPH, "index": 1, "enabled": False, "digest": digest, "confirm": True})
    assert r.status_code == 422 and not CALLS


def test_stale_digest_refused(api):
    c, cid = api
    ST["digest"] = "cd" * 32
    assert toggle(c, cid, DEB, 1, False).status_code == 409 and not writes()
    assert add(c, cid, "test", accept_risk=True).status_code == 409 and not writes()


def test_unreadable_digest_is_a_502_not_a_conflict(api):
    """Un digest illisible chez Proxmox = on ne sait pas : refus « illisible » (502), pas « modifié entre-temps » (409)."""
    c, cid = api
    ST["digest"] = ["pas", "une", "chaîne"]
    assert toggle(c, cid, DEB, 1, False).status_code == 502 and add(c, cid, "test", accept_risk=True).status_code == 502
    assert not writes()


def test_repository_list_is_bounded():
    raw = repos_payload()
    raw["files"][0]["repositories"] = [repo(f"http://x{i}.example") for i in range(250)]
    idx = [r["index"] for r in shape_repositories(raw)["files"][0]["repositories"]]
    assert max(idx) == 200 and len(idx) == 201


def test_confirm_required(api):
    c, cid = api
    assert toggle(c, cid, DEB, 1, False, confirm=False).status_code == 400
    assert add(c, cid, "enterprise", confirm=False).status_code == 400
    assert not writes()


def test_unreadable_state_refuses(api):
    c, cid = api
    ST["read_down"] = True
    assert toggle(c, cid, DEB, 1, False).status_code == 502 and add(c, cid, "test", accept_risk=True).status_code == 502 and not writes()


# ---------------------------------------------------------------- ajouter
def test_add_standard_repo(api):
    c, cid = api
    ST["sub"] = "active"
    assert add(c, cid, "enterprise").status_code == 200
    assert writes() == [("POST", "/nodes/enzo/apt/repositories", f"handle=enterprise&digest={DIGEST}")]


def test_add_test_repo_and_enterprise_without_subscription_need_accept_risk(api):
    c, cid = api
    ST["sub"] = "active"
    r = add(c, cid, "test")
    assert r.status_code == 409 and "TEST" in r.json()["detail"] and not writes()
    assert add(c, cid, "test", accept_risk=True).status_code == 200
    CALLS.clear()
    ST["sub"] = "notfound"
    assert add(c, cid, "enterprise").status_code == 409 and not writes()


def test_add_unknown_or_already_configured(api):
    c, cid = api
    assert add(c, cid, "inconnu").status_code == 404
    assert add(c, cid, "no-subscription").status_code == 409                          # déjà actif
    assert add(c, cid, "ceph-squid-enterprise").status_code == 409                    # configuré mais désactivé : l'activer
    assert not writes()


@pytest.mark.parametrize("handle", ["", "A", "-x", "a b", "a;b", "a/b", "x" * 61, "a\n"])
def test_handle_validated(api, handle):
    c, cid = api
    assert add(c, cid, handle).status_code == 422 and not CALLS


# ---------------------------------------------------------------- transverse
def test_requires_login_and_node_validated(api):
    c, cid = api
    assert c.put("/api/connections/%d/nodes/a;b/apt/repositories" % cid, json={}).status_code in (404, 422)
    c.post("/api/auth/logout")
    assert toggle(c, cid, DEB, 1, False).status_code == 401 and add(c, cid, "test").status_code == 401
    assert not CALLS


def test_unknown_fields_not_forwarded(api):
    c, cid = api
    toggle(c, cid, DEB, 1, False, extra="x", **{"file-type": "list", "command": "rm"})
    assert "extra" not in writes()[0][2] and "command" not in writes()[0][2] and "file-type" not in writes()[0][2]


def test_audit_success_refusal_error_without_secret(api):
    c, cid = api
    toggle(c, cid, DEB, 1, False)
    add(c, cid, "test")                                                                # refusé : risque
    ST["write_fail"] = True
    assert toggle(c, cid, DEB, 0, False).status_code == 502
    log = c.get("/api/audit").json()[::-1]
    assert [(e["action"], e["status"]) for e in log] == [("apt-repo-toggle", "ok"), ("apt-repo-add", "error"), ("apt-repo-toggle", "error")]
    assert SECRET not in c.get("/api/audit").text
