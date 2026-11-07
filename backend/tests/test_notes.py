import httpx
import pytest

from app import notespec as N
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
DIGEST = "ab" * 20
CALLS: list[tuple[str, str, str]] = []
ST: dict = {}


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    CALLS.append((request.method, p, request.content.decode()))
    if p.endswith("/config") and request.method == "GET":
        if ST.get("down"):
            return httpx.Response(500, json={"data": None, "message": SECRET})
        return httpx.Response(200, json={"data": ST.get("cfg", {"description": "# Titre\n<script>x</script>", "digest": ST.get("digest", DIGEST), "memory": 512})})
    if p.endswith("/config") and request.method == "PUT":
        sent = set(httpx.QueryParams(request.content.decode()).keys())
        if sent not in ({"description", "digest"}, {"delete", "digest"}, {"description"}):          # schéma : jamais autre chose ({"description"} seul : config vide)
            return httpx.Response(400, json={"data": None, "message": "Parameter verification failed."})
        if ST.get("fail"):
            return httpx.Response(403, json={"data": None, "message": SECRET})
        return httpx.Response(200, json={"data": None})
    return httpx.Response(404, json={"data": None})


@pytest.fixture
def api(client):
    CALLS.clear()
    ST.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def guest(cid, gtype="qemu", vmid=100, node="enzo"):
    return f"/api/connections/{cid}/guests/{node}/{gtype}/{vmid}/notes"


def node(cid, n="enzo"):
    return f"/api/connections/{cid}/nodes/{n}/notes"


def writes():
    return [x for x in CALLS if x[0] == "PUT"]


def test_read_guest_and_node_notes_returns_only_notes_and_digest(api):
    c, cid = api
    for url in (guest(cid), guest(cid, "lxc", 101), node(cid)):
        r = c.get(url)
        assert r.status_code == 200 and r.json() == {"notes": "# Titre\n<script>x</script>", "digest": DIGEST, "empty": False}      # rien d'autre de la configuration


def test_read_tolerates_garbage(api):
    c, cid = api
    for cfg in ({}, {"description": 5, "digest": "zz"}, {"description": "x" * 10000, "digest": DIGEST}, "texte", None):
        ST["cfg"] = cfg
        r = c.get(guest(cid)).json()
        assert r["notes"] == ("x" * 8192 if isinstance(cfg, dict) and cfg.get("description") == "x" * 10000 else "") and (r["digest"] == DIGEST if isinstance(cfg, dict) and cfg.get("digest") == DIGEST else r["digest"] is None)


def test_write_guest_notes_sends_description_and_digest_only(api):
    c, cid = api
    r = c.put(guest(cid), json={"notes": "Serveur web\r\nligne 2", "digest": DIGEST, "memory": 1, "delete": "net0"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert writes() == [("PUT", "/nodes/enzo/qemu/100/config", f"description=Serveur+web%0Aligne+2&digest={DIGEST}")]        # retours chariot normalisés


def test_write_node_notes(api):
    c, cid = api
    assert c.put(node(cid), json={"notes": "nœud principal", "digest": DIGEST}).status_code == 200
    assert writes()[0][1] == "/nodes/enzo/config" and "description=" in writes()[0][2]


def test_empty_or_blank_notes_delete_the_option(api):
    c, cid = api
    for text in ("", "   \n  "):
        assert c.put(guest(cid), json={"notes": text, "digest": DIGEST}).status_code == 200
    assert [w[2] for w in writes()] == [f"delete=description&digest={DIGEST}"] * 2


def test_stale_digest_refused(api):
    c, cid = api
    ST["digest"] = "cd" * 20
    r = c.put(guest(cid), json={"notes": "x", "digest": DIGEST})
    assert r.status_code == 409 and not writes()


def test_unreadable_or_digestless_config_refuses(api):
    c, cid = api
    ST["down"] = True
    r = c.put(guest(cid), json={"notes": "x", "digest": DIGEST})
    assert r.status_code == 502 and SECRET not in r.text and not writes()
    ST.clear()
    ST["cfg"] = {"description": "a"}                                          # pas de digest lisible
    assert c.put(node(cid), json={"notes": "x", "digest": DIGEST}).status_code == 502 and not writes()


@pytest.mark.parametrize("digest", ["", "zz" * 20, "ab" * 19, "AB" * 20, "ab" * 21, "ab" * 20 + "\n", "x" + "ab" * 20])
def test_digest_validated(api, digest):
    c, cid = api
    assert c.put(guest(cid), json={"notes": "x", "digest": digest}).status_code == 422 and not CALLS


def test_empty_node_config_can_be_written_without_digest(api):
    """Cas réel : la configuration d'un nœud sans réglage est `{}` (aucun digest chez Proxmox)."""
    c, cid = api
    ST["cfg"] = {}
    assert c.get(node(cid)).json() == {"notes": "", "digest": None, "empty": True}
    assert c.put(node(cid), json={"notes": "premier réglage du nœud"}).status_code == 200
    assert writes() == [("PUT", "/nodes/enzo/config", "description=premier+r%C3%A9glage+du+n%C5%93ud")]


def test_empty_config_guards(api):
    c, cid = api
    ST["cfg"] = {}
    assert c.put(node(cid), json={"notes": "x", "digest": DIGEST}).status_code == 409 and not writes()      # un digest alors qu'il n'y en a pas : périmé
    assert c.put(node(cid), json={"notes": "   "}).status_code == 200 and not writes()                       # rien à supprimer : aucune écriture


def test_digest_required_when_config_has_one(api):
    c, cid = api
    r = c.put(guest(cid), json={"notes": "x"})
    assert r.status_code == 400 and not writes()


def test_guest_read_path_validated(api):
    c, cid = api
    for path in ("enzo/vm/100", "enzo/qemu/99", "a;b/qemu/100"):
        assert c.get(f"/api/connections/{cid}/guests/{path}/notes").status_code in (404, 422)
    assert not CALLS


def test_notes_bounded_and_nul_refused(api):
    c, cid = api
    assert c.put(guest(cid), json={"notes": "x" * 8193, "digest": DIGEST}).status_code == 422
    assert c.put(guest(cid), json={"notes": "a\x00b", "digest": DIGEST}).status_code == 422
    assert c.put(guest(cid), json={"notes": "x" * 8192, "digest": DIGEST}).status_code == 200
    assert len(writes()) == 1


@pytest.mark.parametrize("path", ["enzo/vm/100", "enzo/qemu/99", "enzo/qemu/abc", "a;b/qemu/100", "enzo/qemu/1000000000"])
def test_guest_path_validated(api, path):
    c, cid = api
    assert c.put(f"/api/connections/{cid}/guests/{path}/notes", json={"notes": "x", "digest": DIGEST}).status_code in (404, 422) and not writes()


def test_node_name_validated_and_login_required(api):
    c, cid = api
    assert c.put(node(cid, "a;b"), json={"notes": "x", "digest": DIGEST}).status_code in (404, 422) and not CALLS
    c.post("/api/auth/logout")
    assert c.get(guest(cid)).status_code == 401 and c.put(node(cid), json={"notes": "x", "digest": DIGEST}).status_code == 401 and not CALLS


def test_audit_never_contains_the_text(api):
    c, cid = api
    c.put(guest(cid), json={"notes": "MOT-DE-PASSE-DANS-LES-NOTES", "digest": DIGEST})
    c.put(node(cid), json={"notes": "autre", "digest": "cd" * 20})                   # refusé : digest périmé
    ST["fail"] = True
    assert c.put(guest(cid), json={"notes": "encore", "digest": DIGEST}).status_code == 502
    log = c.get("/api/audit").json()[::-1]
    assert [(e["action"], e["status"]) for e in log] == [("guest-notes", "ok"), ("node-notes", "error"), ("guest-notes", "error")]
    text = c.get("/api/audit").text
    assert "MOT-DE-PASSE" not in text and "encore" not in text and SECRET not in text and log[0]["target"] == "qemu/100@enzo"


def test_unit_helpers():
    assert N.write_params(N.NotesBody(notes="a", digest=DIGEST)) == {"description": "a", "digest": DIGEST}
    assert N.write_params(N.NotesBody(notes="a")) == {"description": "a"} and N.shape_notes({})["empty"] is True and N.shape_notes({"memory": 1})["empty"] is False
    assert N.write_params(N.NotesBody(notes=" ", digest=DIGEST)) == {"delete": "description", "digest": DIGEST}
