"""Cloud-init avancé (`cicustom`, snippets) : faux Proxmox STRICT (digest vérifié, volumes vérifiés, format exact, 400 sinon)."""
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient
from app.routers.cloudinit import CloudInitUpdate, merge_cicustom, parse_cicustom, shape

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
U, N, M, V = "local:snippets/ci-user.yaml", "local:snippets/ci-net.yaml", "nfs-ci:snippets/meta.yml", "local:snippets/vendor.yaml"
ST: dict = {}
WRITES: list = []


def fresh():
    WRITES.clear(); ST.clear()
    ST.update(cfg={"name": "kaji-sandbox", "ide2": "local-lvm:vm-115-cloudinit,media=cdrom", "digest": "d" * 40},
              storages=[{"storage": "local", "active": 1}, {"storage": "nfs-ci", "active": 1}, {"storage": "off", "active": 0}, {"storage": "broken", "active": 1}],
              files={"local": [{"volid": U, "size": 120}, {"volid": N, "size": 80}, {"volid": V, "size": 5}, {"volid": "nfs-ci:snippets/ignore-me.yaml"}, {"volid": "local:snippets/../evil"},
                               {"volid": "local:iso/not-a-snippet.iso", "size": 1}, "junk"],
                     "nfs-ci": [{"volid": M, "size": True}], "off": [{"volid": "off:snippets/never.yaml"}]})


def bad(msg):
    return httpx.Response(400, json={"data": None, "message": msg})


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    q = dict(request.url.params)
    if request.method == "GET":
        if p == "/nodes/enzo/qemu/115/config":
            assert q == {"current": "1"}
            return httpx.Response(200, json={"data": ST["cfg"]})
        if p == "/nodes/enzo/storage":
            assert q == {"content": "snippets"}
            return httpx.Response(200, json={"data": ST["storages"]})
        if p.startswith("/nodes/enzo/storage/") and p.endswith("/content"):
            assert q == {"content": "snippets"}
            name = p.split("/")[4]
            if name == "broken":
                return httpx.Response(500, json={"data": None, "message": "storage offline"})
            return httpx.Response(200, json={"data": ST["files"].get(name, [])})
        return httpx.Response(404, json={"data": None})
    body = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    assert request.method == "PUT" and p == "/nodes/enzo/qemu/115/config"
    if "digest" in body and body["digest"] != ST["cfg"]["digest"]:
        return bad("detected modified configuration - file changed by other user? Try again.")
    if "cicustom" in body:
        known = {v["volid"] for rows in ST["files"].values() for v in rows if isinstance(v, dict)}
        for item in body["cicustom"].split(","):
            part, _, volid = item.partition("=")
            if part not in ("user", "network", "meta", "vendor") or volid not in known:
                return bad(f"cicustom: invalid format - {item}")
    WRITES.append((request.method, p, body))
    for k, v in body.items():
        if k == "delete":
            for d in v.split(","):
                ST["cfg"].pop(d, None)
        elif k != "digest":
            ST["cfg"][k] = v
    return httpx.Response(200, json={"data": None})


@pytest.fixture
def api(client):
    fresh()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def u(cid, suffix=""):
    return f"/api/connections/{cid}/guests/enzo/qemu/115/cloudinit{suffix}"


# ---------- fonctions pures ----------

def test_parse_cicustom_keeps_only_valid_parts():
    raw = f"user={U},network={N},meta={M},vendor={V},evil=local:snippets/x,user2=local:snippets/y,network=local:iso/z,meta=local:snippets/../x"
    assert parse_cicustom(raw) == {"user": U, "network": N, "meta": M, "vendor": V}
    assert parse_cicustom(None) == {} and parse_cicustom("") == {} and parse_cicustom("n'importe quoi,=,user") == {}


def test_merge_keeps_canonical_order_and_drops_empty_parts():
    assert merge_cicustom({"network": N}, {"user": U}) == f"user={U},network={N}"
    assert merge_cicustom({"user": U, "network": N}, {"user": None}) == f"network={N}"
    assert merge_cicustom({"user": U}, {"user": None}) is None
    assert merge_cicustom({"user": U}, {"user": N}) == f"user={N}"


@pytest.mark.parametrize("bad", [
    {"user": "local:iso/a.iso"}, {"user": "local:snippets/../x"}, {"user": "local:snippets/a,network=local:snippets/b"}, {"user": "local:snippets/a b"},
    {"user": "snippets/a.yaml"}, {"user": "local:snippets/"}, {"user": "-x:snippets/a"}, {"user": "local:snippets/" + "a" * 202}, {"user": "local:snippets/a\nb"},
    {"user": "local:snippets/a;rm"}, {"evil": "local:snippets/a"}, {"user": 5},
])
def test_invalid_custom_is_rejected(bad):
    with pytest.raises(ValidationError):
        CloudInitUpdate(custom=bad)


def test_empty_custom_value_means_remove():
    assert CloudInitUpdate(custom={"user": "", "network": "  ", "meta": None}).custom == {"user": None, "network": None, "meta": None}


def test_shape_exposes_custom_parts():
    s = shape({"cicustom": f"user={U},vendor={V}", "ide2": "local-lvm:vm-115-cloudinit,media=cdrom"})
    assert s["custom"] == {"user": U, "network": None, "meta": None, "vendor": V}
    assert shape({"name": "x"})["custom"] == {"user": None, "network": None, "meta": None, "vendor": None}


# ---------- lecture des snippets ----------

def test_requires_auth(client):
    assert client.get(u(1, "/snippets")).status_code == 401


def test_snippets_listing_is_filtered_shaped_and_tolerates_a_broken_storage(api):
    c, cid = api
    r = c.get(u(cid, "/snippets"))
    assert r.status_code == 200
    expected = [{"volid": U, "storage": "local", "name": "ci-user.yaml", "size": 120}, {"volid": N, "storage": "local", "name": "ci-net.yaml", "size": 80},
                {"volid": V, "storage": "local", "name": "vendor.yaml", "size": 5}, {"volid": M, "storage": "nfs-ci", "name": "meta.yml", "size": None}]
    # ni ../evil, ni une ISO, ni le volume d'un autre stockage, ni un stockage inactif ; la taille booléenne est écartée ; le stockage illisible est signalé
    assert r.json() == {"snippets": sorted(expected, key=lambda f: f["volid"]), "errors": ["broken"]} and SECRET not in r.text


# ---------- écriture ----------

def test_set_user_snippet_sends_cicustom_with_digest(api):
    c, cid = api
    r = c.patch(u(cid), json={"custom": {"user": U}})
    assert r.status_code == 200 and r.json() == {"changed": ["cicustom"], "cleared": []}
    assert WRITES == [("PUT", "/nodes/enzo/qemu/115/config", {"cicustom": f"user={U}", "digest": "d" * 40})]


def test_adding_a_part_keeps_the_others_and_foreign_parts_are_dropped_from_the_rewrite(api):
    c, cid = api
    ST["cfg"]["cicustom"] = f"user={U}"
    assert c.patch(u(cid), json={"custom": {"network": N, "meta": M}}).status_code == 200
    assert WRITES[0][2]["cicustom"] == f"user={U},network={N},meta={M}"


def test_removing_one_part_rewrites_and_removing_all_deletes_the_key(api):
    c, cid = api
    ST["cfg"]["cicustom"] = f"user={U},network={N}"
    assert c.patch(u(cid), json={"custom": {"user": None}}).status_code == 200
    assert WRITES[0][2]["cicustom"] == f"network={N}"
    assert c.patch(u(cid), json={"custom": {"network": ""}}).status_code == 200
    assert WRITES[1][2] == {"delete": "cicustom", "digest": "d" * 40} and "cicustom" not in ST["cfg"]


def test_unchanged_custom_writes_nothing(api):
    c, cid = api
    ST["cfg"]["cicustom"] = f"user={U}"
    r = c.patch(u(cid), json={"custom": {"user": U}})
    assert r.status_code == 200 and r.json() == {"changed": [], "cleared": []} and WRITES == []
    assert c.patch(u(cid), json={"custom": {"meta": None}}).status_code == 200 and WRITES == []          # retirer ce qui n'est pas défini : rien à faire


def test_unknown_snippet_is_refused_before_any_write(api):
    c, cid = api
    for volid in ("local:snippets/absent.yaml", "off:snippets/never.yaml", "nfs-ci:snippets/ci-user.yaml", "other:snippets/x.yaml"):
        r = c.patch(u(cid), json={"custom": {"user": volid}})
        assert r.status_code == 422 and "introuvable" in r.json()["detail"] and volid not in r.text, volid
    assert WRITES == []


def test_hostile_values_never_reach_proxmox(api):
    c, cid = api
    for bad in ("local:snippets/a,network=local:snippets/b", "local:snippets/../x", "local:iso/x.iso", "x" * 5):
        assert c.patch(u(cid), json={"custom": {"user": bad}}).status_code == 422
    assert WRITES == []


def test_custom_combines_with_other_settings_in_one_write(api):
    c, cid = api
    r = c.patch(u(cid), json={"user": "kaji", "custom": {"vendor": V}, "clear": ["upgrade"]})
    assert r.status_code == 200
    assert WRITES == [("PUT", "/nodes/enzo/qemu/115/config", {"ciuser": "kaji", "cicustom": f"vendor={V}", "delete": "ciupgrade", "digest": "d" * 40})]


def test_stale_digest_is_refused_by_proxmox(api):
    c, cid = api
    orig = _handler

    def handler(request):
        if request.method == "PUT":
            ST["cfg"]["digest"] = "e" * 40                                                         # la config a changé après la lecture
        return orig(request)
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(handler)))
    assert c.patch(u(cid), json={"custom": {"user": U}}).status_code == 502 and WRITES == []


def test_audit_names_the_parts_not_the_files_and_logs_refusals(api):
    c, cid = api
    c.patch(u(cid), json={"custom": {"user": U}})
    c.patch(u(cid), json={"custom": {"user": "local:snippets/absent.yaml"}})
    log = c.get("/api/audit").json()[::-1]
    assert [(e["action"], e["status"]) for e in log] == [("cloudinit-update", "started"), ("cloudinit-update", "error")]
    assert "snippets user=défini" in log[0]["detail"] and "ci-user.yaml" not in log[0]["detail"] and SECRET not in c.get("/api/audit").text


def test_audit_detail_has_no_empty_modified_part_when_only_removing(api):
    c, cid = api
    ST["cfg"]["cicustom"] = f"user={U}"
    c.patch(u(cid), json={"custom": {"user": None}})
    c.patch(u(cid), json={"user": "kaji"})
    log = [e["detail"] for e in c.get("/api/audit").json()[::-1]]
    assert log == ["supprimé : cicustom · snippets user=retiré", "modifié : ciuser"]
