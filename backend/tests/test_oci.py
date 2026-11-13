import re
from urllib.parse import parse_qs

import httpx
import pytest

from app import ocispec as O
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
UPID = "UPID:enzo:0001:0002:0003:imgcopy::kaji@pve!kaji:"
SEEN: list[httpx.Request] = []
WRITES: list[dict] = []
ST: dict = {}


def _handler(request: httpx.Request) -> httpx.Response:
    SEEN.append(request)
    p = request.url.path.removeprefix("/api2/json")
    if ST.get("fail"):
        return httpx.Response(403, json={"data": None, "message": SECRET})
    if request.method == "GET" and p == "/nodes/enzo/query-oci-repo-tags":
        ref = request.url.params.get("reference", "")
        if set(request.url.params) != {"reference"} or ":" in ref.split("/")[-1]:
            return httpx.Response(400, json={"data": None, "message": "Parameter verification failed."})
        return httpx.Response(200, json={"data": ST.get("tags", ["latest", "3.20", {"tag": "edge"}])})
    mm = re.fullmatch(r"/nodes/enzo/storage/([^/]+)/oci-registry-pull", p)
    if request.method == "POST" and mm:
        body = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if set(body) - {"reference", "filename"} or "reference" not in body or not O.REFERENCE.fullmatch(body["reference"]):
            return httpx.Response(400, json={"data": None, "message": "Parameter verification failed."})
        if ST.get("exists"):
            return httpx.Response(500, json={"data": None, "message": "refusing to override existing file"})
        WRITES.append({"storage": mm.group(1), **body})
        return httpx.Response(200, json={"data": UPID})
    return httpx.Response(404, json={"data": None, "message": "route inconnue du faux Proxmox"})


@pytest.fixture
def api(client):
    SEEN.clear(); WRITES.clear(); ST.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def tags(c, cid, ref, node="enzo"):
    return c.get(f"/api/connections/{cid}/nodes/{node}/oci/tags", params={"reference": ref})


def pull(c, cid, storage="local", **body):
    return c.post(f"/api/connections/{cid}/nodes/enzo/storage/{storage}/oci-pull", json={"confirm": True, **body})


def audit_text(c):
    return c.get("/api/audit").text


# ------------------------------------------------------------------ étiquettes
def test_tags_are_listed_and_sanitised(api):
    c, cid = api
    r = tags(c, cid, "library/alpine")
    assert r.status_code == 200 and r.json() == {"tags": ["latest", "3.20", "edge"]}
    assert SEEN[-1].url.params["reference"] == "library/alpine"
    ST["tags"] = ["ok", "mauvaise étiquette", "x" * 200, 5, None, {"tag": "a/b"}, "ok", {"nope": 1}, "v1.2-rc_3"]
    assert tags(c, cid, "alpine").json() == {"tags": ["ok", "v1.2-rc_3"]}
    ST["tags"] = {"a": 1}
    assert tags(c, cid, "alpine").json() == {"tags": []}


def test_tag_list_is_bounded(api):
    c, cid = api
    ST["tags"] = [f"t{i}" for i in range(2000)]
    got = tags(c, cid, "alpine").json()["tags"]
    assert len(got) == O.MAX_TAGS and got[0] == "t0"
    ST["tags"] = ["x"] * 1500 + [f"t{i}" for i in range(600)]            # beaucoup de doublons : la borne d'entrée limite le travail
    assert len(tags(c, cid, "alpine").json()["tags"]) <= O.MAX_TAGS


@pytest.mark.parametrize("ref", ["alpine:latest", "", "Alpine", "a b", "a//b", "-x", "ghcr.io/", "x" * 400, "alpine\n", "alpine:", "../etc", "ａlpine"])
def test_tags_refuses_invalid_repositories_without_calling_proxmox(api, ref):
    c, cid = api
    r = tags(c, cid, ref)
    assert r.status_code in (422,) and not SEEN


@pytest.mark.parametrize("ref", ["localhost/alpine", "localhost:5000/alpine", "foo.localhost/x", "127.0.0.1/alpine", "127.0.0.1:5000/alpine", "0.0.0.0/x", "169.254.169.254/x", "224.0.0.1/x"])
def test_local_registries_are_refused(api, ref):
    c, cid = api
    assert tags(c, cid, ref).status_code == 422 and not SEEN
    assert pull(c, cid, reference=ref + ":latest").status_code == 422 and not WRITES


def test_private_network_and_public_registries_are_accepted(api):
    c, cid = api
    for ref in ("registry.local.example/team/app", "10.0.0.7:5000/app", "ghcr.io/owner/app", "docker.io/library/alpine"):
        assert tags(c, cid, ref).status_code == 200, ref


# ------------------------------------------------------------------ téléchargement
def test_pull_needs_confirm(api):
    c, cid = api
    r = c.post(f"/api/connections/{cid}/nodes/enzo/storage/local/oci-pull", json={"reference": "alpine:3.20"})
    assert r.status_code == 400 and not WRITES


def test_pull_sends_only_the_reference_and_the_filename(api):
    c, cid = api
    r = pull(c, cid, reference="library/alpine:3.20", filename="alpine-3.20")
    assert r.status_code == 202 and r.json() == {"upid": UPID, "node": "enzo"}
    assert WRITES == [{"storage": "local", "reference": "library/alpine:3.20", "filename": "alpine-3.20"}]
    assert pull(c, cid, reference="alpine:latest").status_code == 202 and WRITES[-1] == {"storage": "local", "reference": "alpine:latest"}


@pytest.mark.parametrize("body", [
    {"reference": "alpine"}, {"reference": "alpine:"}, {"reference": "Alpine:latest"}, {"reference": "a b:latest"}, {"reference": "alpine:lat est"}, {"reference": "alpine:latest\n"},
    {"reference": "alpine:" + "x" * 200}, {"reference": "ghcr.io:5000x/app:1"}, {"reference": "alpine:latest", "filename": "../x"}, {"reference": "alpine:latest", "filename": "a/b"},
    {"reference": "alpine:latest", "filename": ""}, {"reference": "alpine:latest", "filename": "é"}, {"reference": "alpine:latest", "filename": ".x"}, {"reference": "alpine:latest", "filename": "x" * 150},
    {"reference": "alpine:latest", "filename": "a b"}, {"reference": "ａlpine:latest"}, {"reference": "alpine:latest", "confirm": "oui"},
    {"reference": "alpine:latest", "filename": "a..b"}, {"reference": "alpine:latest", "filename": "x.."},
])
def test_invalid_pulls_never_reach_proxmox(api, body):
    c, cid = api
    r = c.post(f"/api/connections/{cid}/nodes/enzo/storage/local/oci-pull", json={"confirm": True, **body})
    assert r.status_code in (400, 422) and not WRITES


def test_invalid_storage_is_refused(api):
    c, cid = api
    for s in ("a b", "-x", "x" * 60, "a;b"):
        assert pull(c, cid, storage=s, reference="alpine:latest").status_code in (404, 422)
    assert not WRITES


def test_existing_image_and_forbidden_are_audited_without_leak(api):
    c, cid = api
    ST["exists"] = True
    assert pull(c, cid, reference="alpine:latest").status_code >= 400
    ST.clear(); ST["fail"] = True
    r = pull(c, cid, reference="alpine:latest")
    assert r.status_code >= 400 and SECRET not in r.text and SECRET not in audit_text(c)
    assert ("storage-oci-pull", "error") in {(a["action"], a["status"]) for a in c.get("/api/audit").json()}


def test_audit_has_the_upid_and_no_filename(api):
    c, cid = api
    pull(c, cid, reference="alpine:latest", filename="mon-fichier")
    t = audit_text(c)
    assert "storage-oci-pull" in t and UPID in t and "mon-fichier" not in t


def test_requires_a_kaji_login(client):
    assert client.get("/api/connections/1/nodes/enzo/oci/tags", params={"reference": "alpine"}).status_code == 401
    assert client.post("/api/connections/1/nodes/enzo/storage/local/oci-pull", json={"reference": "alpine:1", "confirm": True}).status_code == 401
