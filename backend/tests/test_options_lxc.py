"""Options d'un conteneur LXC (lot #145) : faux Proxmox STRICT. RIEN n'a tourné sur un vrai cluster.

Le faux n'accepte, sur `PUT …/lxc/{vmid}/config`, que les paramètres du schéma réel relevé par PC A : tout autre paramètre répond 400.
"""
import re
from urllib.parse import parse_qs

import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
DIGEST = "a" * 40
ALLOWED = {"arch", "cmode", "console", "delete", "description", "digest", "features", "hookscript", "hostname", "lock", "onboot", "ostype", "protection", "revert",
           "startup", "tags", "timezone", "tty", "unprivileged"}
CFG0 = {"hostname": "kaji-ct", "unprivileged": 1, "arch": "amd64", "digest": DIGEST, "hookscript": "local:snippets/h.pl", "lock": "backup", "memory": 512,
        "lxc.cgroup2.devices.allow": "a", "rootfs": "local-lvm:vm-118-disk-0,size=4G"}
CALLS: list[dict] = []
STATE: dict = {}


def _json(code, body, reason="OK"):
    return httpx.Response(code, json=body, extensions={"reason_phrase": reason.encode()})


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()} if request.content else {}
    CALLS.append({"method": request.method, "path": p, "params": dict(request.url.params), "form": form})
    if STATE.get("fail"):
        m, path, code = STATE["fail"]
        if (request.method, p) == (m, path):
            return _json(code, {"data": None}, "Permission check failed (/, Sys.Modify)" if code == 403 else "Internal Server Error")
    if request.method == "GET" and p == "/nodes/enzo/lxc/118/config":
        return _json(200, {"data": STATE.get("cfg", CFG0)})
    if request.method == "GET" and p == "/nodes/enzo/lxc/118/pending":
        return _json(200, {"data": STATE.get("pending", [])})
    if request.method == "PUT" and p == "/nodes/enzo/lxc/118/config":
        had = re.search(r"(^|,)(keyctl|fuse|mount)=", STATE.get("cfg", CFG0).get("features", ""))
        if STATE.get("root_only") and (re.search(r"(^|,)(keyctl|fuse|mount)=", form.get("features", "")) or ("features" in form.get("delete", "").split(",") and had)):
            return _json(403, {"data": None}, "Permission check failed (changing feature flags (except nesting) is only allowed for root@pam)")
        return _json(400, {"data": None}) if set(form) - ALLOWED else _json(200, {"data": None})
    return _json(404, {"data": None})


@pytest.fixture
def api(client):
    CALLS.clear()
    STATE.clear()
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def u(cid, vmid=118, node="enzo"):
    return f"/api/connections/{cid}/guests/{node}/lxc/{vmid}/options"


def cfg(**kw):
    return {**CFG0, **kw}


def writes():
    return [c for c in CALLS if c["method"] != "GET"]


def audit(c):
    return c.get("/api/audit").json()[::-1]


def patch(c, cid, **body):
    return c.patch(u(cid), json=body)


def is_confirmation(r):
    return r.status_code == 400 and r.json()["detail"].startswith("Confirmation requise (renvoie la requête avec confirm=true) : ")


# ============================== accès ==============================================================================

def test_requires_auth(client):
    assert client.get("/api/connections/1/guests/enzo/lxc/118/options").status_code == 401
    assert client.patch("/api/connections/1/guests/enzo/lxc/118/options", json={"onboot": True}).status_code == 401


def test_unknown_connection(api):
    c, _ = api
    assert c.get(u(999)).status_code == 404 and c.patch(u(999), json={"onboot": True}).status_code == 404 and CALLS == []


@pytest.mark.parametrize("vmid,node", [(99, "enzo"), (1000000000, "enzo"), ("x", "enzo"), (118, "a;b"), (118, "-x")])
def test_invalid_path_is_refused_and_nothing_is_called(api, vmid, node):
    c, cid = api
    assert c.get(u(cid, vmid, node)).status_code in (404, 422) and c.patch(u(cid, vmid, node), json={"onboot": True}).status_code in (404, 422) and CALLS == []


@pytest.mark.parametrize("method", ["put", "post", "delete"])
def test_no_other_verb(api, method):
    c, cid = api
    assert getattr(c, method)(u(cid)).status_code in (404, 405, 422) and CALLS == []


# ============================== lecture ============================================================================

def test_get_shapes_every_field(api):
    c, cid = api
    STATE["cfg"] = cfg(onboot=1, startup="order=3,up=10", protection=1, features="nesting=1,fuse=0,keyctl=1,mount=nfs;cifs,mknod=1", ostype="debian", console=1,
                       cmode="tty", tty=4, timezone="Europe/Paris", description="CT de test")
    STATE["pending"] = [{"key": "features", "value": "nesting=1", "pending": "nesting=0"}, {"key": "memory", "value": 512, "pending": 1024}]
    d = c.get(u(cid)).json()
    assert [(x["path"], x["params"]) for x in CALLS] == [("/nodes/enzo/lxc/118/config", {"current": "1"}), ("/nodes/enzo/lxc/118/pending", {})]
    o = d["options"]
    assert (o["onboot"], o["protection"], o["console"]) == (True, True, True) and o["startup"] == {"order": 3, "up": 10, "down": None}
    assert o["features"] == {"nesting": True, "fuse": False, "keyctl": True, "mount": ["cifs", "nfs"]}
    assert (o["ostype"], o["cmode"], o["tty"], o["timezone"], o["description"]) == ("debian", "tty", 4, "Europe/Paris", "CT de test")
    assert d["unprivileged"] is True and d["type"] == "lxc" and d["reboot_required"] is True
    assert d["pending"] == [{"key": "features", "value": "nesting=1", "pending": "nesting=0", "delete": False}]


def test_get_absent_settings_are_none_and_unmanaged_keys_are_never_shown(api):
    c, cid = api
    r = c.get(u(cid))
    assert all(v is None for v in r.json()["options"].values()) and r.json()["pending"] == []
    assert all(w not in r.text for w in ("hookscript", "lxc.cgroup2", "backup", "local-lvm"))


@pytest.mark.parametrize("raw,expected", [("2", 2), (3, 3), ("7", None), (7, None), ("x", None), (True, None), (-1, None), ("٣", None)])
def test_get_tty_garbage(api, raw, expected):
    c, cid = api
    STATE["cfg"] = cfg(tty=raw)
    assert c.get(u(cid)).json()["options"]["tty"] == expected


def test_get_tolerates_garbage_values(api):
    c, cid = api
    STATE["cfg"] = cfg(ostype="../x", cmode="evil", timezone="a b", features="???", description=5, onboot="peut-être")
    o = c.get(u(cid)).json()["options"]
    assert o["ostype"] is None and o["cmode"] is None and o["timezone"] is None and o["description"] is None and o["onboot"] is None
    assert o["features"] == {"nesting": None, "fuse": None, "keyctl": None, "mount": []}


# ============================== écriture : paramètres exacts =======================================================

@pytest.mark.parametrize("body,form", [
    ({"onboot": True}, {"onboot": "1"}), ({"onboot": False}, {"onboot": "0"}), ({"protection": True}, {"protection": "1"}), ({"console": False}, {"console": "0"}),
    ({"ostype": "alpine"}, {"ostype": "alpine"}), ({"cmode": "console"}, {"cmode": "console"}), ({"tty": 0}, {"tty": "0"}), ({"tty": 6}, {"tty": "6"}),
    ({"timezone": "host"}, {"timezone": "host"}), ({"timezone": "Europe/Paris"}, {"timezone": "Europe/Paris"}), ({"timezone": "America/Argentina/Buenos_Aires"}, {"timezone": "America/Argentina/Buenos_Aires"}),
    ({"description": "a\nb"}, {"description": "a\nb"}),
    ({"startup": {"order": 1, "up": 2, "down": 3}}, {"startup": "order=1,up=2,down=3"}),
    ({"features": {"nesting": True}}, {"features": "nesting=1"}), ({"features": {"nesting": True, "keyctl": True, "fuse": False}}, {"features": "nesting=1,fuse=0,keyctl=1"}),
    ({"features": {"mount": ["cifs", "nfs"]}}, {"features": "mount=cifs;nfs"}),
    ({"features": {"mount": ["nfs", "cifs"]}}, {"features": "mount=cifs;nfs"}),
])
def test_patch_sends_exact_params_with_the_digest(api, body, form):
    c, cid = api
    r = patch(c, cid, **body)
    assert r.status_code == 200 and r.json()["changed"] == sorted(form) and r.json()["removed"] == []
    assert len(writes()) == 1 and writes()[0]["method"] == "PUT" and writes()[0]["path"] == "/nodes/enzo/lxc/118/config"
    assert writes()[0]["form"] == {**form, "digest": DIGEST}


def test_features_keep_the_properties_kaji_does_not_manage(api):
    c, cid = api
    STATE["cfg"] = cfg(features="nesting=0,mknod=1,force_rw_sys=1")
    patch(c, cid, features={"nesting": True})
    assert writes()[0]["form"]["features"] == "nesting=1,mknod=1,force_rw_sys=1"


def test_features_keep_values_that_are_not_changed(api):
    c, cid = api
    STATE["cfg"] = cfg(features="nesting=1,keyctl=1,mount=nfs")
    patch(c, cid, features={"fuse": True})
    assert writes()[0]["form"]["features"] == "nesting=1,fuse=1,keyctl=1,mount=nfs"


def test_features_empty_mount_list_removes_mount_only(api):
    c, cid = api
    STATE["cfg"] = cfg(features="nesting=1,mount=nfs;cifs")
    patch(c, cid, features={"mount": []})
    assert writes()[0]["form"]["features"] == "nesting=1"


def test_features_that_would_become_empty_are_refused_not_sent_blank(api):
    c, cid = api
    STATE["cfg"] = cfg(features="mount=nfs")
    r = patch(c, cid, features={"mount": []})
    assert r.status_code == 422 and writes() == []


def test_an_unreadable_features_property_refuses_the_change_instead_of_dropping_it(api):
    c, cid = api
    STATE["cfg"] = cfg(features="nesting=1,mknod=a b;evil")
    assert patch(c, cid, features={"nesting": False}).status_code == 422 and writes() == []


def test_startup_keeps_the_values_that_are_not_changed(api):
    c, cid = api
    STATE["cfg"] = cfg(startup="order=2,up=30,down=60")
    patch(c, cid, startup={"up": 45})
    assert writes()[0]["form"]["startup"] == "order=2,up=45,down=60"


def test_without_a_valid_digest_none_is_sent(api):
    c, cid = api
    STATE["cfg"] = {k: v for k, v in cfg().items() if k != "digest"}
    patch(c, cid, onboot=True)
    assert "digest" not in writes()[0]["form"]


# ============================== retrait ============================================================================

def test_clear_goes_in_one_delete_parameter(api):
    c, cid = api
    r = patch(c, cid, clear=["features", "tty", "timezone"])
    assert r.json() == {"changed": [], "removed": ["features", "tty", "timezone"]} and writes()[0]["form"] == {"delete": "features,tty,timezone", "digest": DIGEST}


def test_a_setting_cannot_be_set_and_cleared_at_once(api):
    c, cid = api
    assert patch(c, cid, tty=2, clear=["tty"]).status_code == 422 and writes() == []


@pytest.mark.parametrize("key", ["hookscript", "lock", "hostname", "arch", "unprivileged", "memory", "rootfs", "digest", "delete", "tags", "../x", "onboot,tty", ""])
def test_clear_only_accepts_the_whitelist(api, key):
    c, cid = api
    assert patch(c, cid, clear=[key]).status_code == 422 and CALLS == []


# ============================== validation =========================================================================

@pytest.mark.parametrize("body", [
    {"onboot": "yes"}, {"onboot": 1}, {"protection": "true"}, {"console": 0},
    {"ostype": "../x"}, {"ostype": "windows"}, {"ostype": "l26"}, {"cmode": "evil"}, {"cmode": ""},
    {"tty": 7}, {"tty": -1}, {"tty": "2"}, {"tty": 1.5}, {"tty": True},
    {"timezone": "a b"}, {"timezone": "../etc"}, {"timezone": "/etc/passwd"}, {"timezone": "Europe/Paris\n"}, {"timezone": "a/b/c/d"}, {"timezone": ""}, {"timezone": "x" * 71},
    {"description": "x" * 8193}, {"description": "a\x00b"}, {"description": 3},
    {"startup": {}}, {"startup": {"order": -1}}, {"startup": {"order": 10000}}, {"startup": {"up": 86401}},
    {"features": {}}, {"features": {"nesting": "1"}}, {"features": {"nesting": 1}}, {"features": {"mount": ["ext4"]}}, {"features": {"mount": ["nfs", "nfs"]}},
    {"features": {"mount": "nfs"}}, {"features": {"mount": ["nfs;cifs"]}}, {"features": "nesting=1"}, {"features": {"mknod": True}},
    {"confirm": "true"}, {"confirm": 1}, {"clear": "onboot"},
])
def test_invalid_values_are_refused_and_nothing_is_called(api, body):
    c, cid = api
    assert patch(c, cid, **body).status_code == 422 and CALLS == []


@pytest.mark.parametrize("body", [{"unprivileged": False}, {"unprivileged": True}, {"arch": "i386"}, {"arch": "amd64"}, {"unprivileged": 0, "onboot": True},
                                  {"arch": "arm64", "onboot": True, "confirm": True}])
def test_unprivileged_and_arch_are_not_modifiable_whatever_else_is_sent(api, body):
    c, cid = api
    r = patch(c, cid, **body)
    assert r.status_code == 422 and CALLS == []


def test_the_validation_error_does_not_echo_the_value(api):
    c, cid = api
    r = patch(c, cid, timezone=SECRET + " x")
    assert r.status_code == 422 and SECRET not in r.text


def test_empty_patch_is_400_and_calls_nothing(api):
    c, cid = api
    assert patch(c, cid).status_code == 400 and patch(c, cid, confirm=True).status_code == 400 and CALLS == []


@pytest.mark.parametrize("extra", [{"hookscript": "x"}, {"lock": "backup"}, {"hostname": "autre"}, {"memory": 9999}, {"delete": "rootfs"}, {"digest": "b" * 40},
                                   {"revert": "memory"}, {"tags": "x"}, {"lxc.cgroup2.devices.allow": "a"}, {"net0": "x"}, {"node": "pve9"}])
def test_unknown_fields_are_ignored_and_never_forwarded(api, extra):
    c, cid = api
    assert patch(c, cid, onboot=True, **extra).status_code == 200
    assert writes()[0]["form"] == {"onboot": "1", "digest": DIGEST}


def test_only_unknown_fields_means_no_change(api):
    c, cid = api
    assert patch(c, cid, hookscript="x", lock="backup").status_code == 400 and CALLS == []


# ============================== risques et confirmation ============================================================

@pytest.mark.parametrize("body", [{"protection": False}, {"clear": ["protection"]}])
def test_removing_the_protection_needs_a_server_side_confirmation(api, body):
    c, cid = api
    STATE["cfg"] = cfg(protection=1)
    r = patch(c, cid, **body)
    assert is_confirmation(r) and "protection" in r.json()["detail"] and writes() == []
    assert patch(c, cid, **body, confirm=True).status_code == 200 and len(writes()) == 1


@pytest.mark.parametrize("body,current", [({"protection": True}, {}), ({"protection": False}, {}), ({"protection": False}, {"protection": 0}), ({"clear": ["protection"]}, {}),
                                          ({"features": {"nesting": False}}, {"features": "nesting=1"}), ({"onboot": False}, {"onboot": 1})])
def test_safe_or_unchanged_settings_need_no_confirmation(api, body, current):
    c, cid = api
    STATE["cfg"] = cfg(**current)
    assert patch(c, cid, **body).status_code == 200


def test_confirm_is_never_forwarded_to_proxmox(api):
    c, cid = api
    STATE["cfg"] = cfg(protection=1)
    patch(c, cid, protection=False, confirm=True)
    assert "confirm" not in writes()[0]["form"] and "confirm" not in writes()[0]["params"]


# ============================== protection de Kaji (KAJI_PROTECTED_VMIDS) ==========================================

@pytest.fixture
def protected(monkeypatch):
    monkeypatch.setattr("app.routers.options.get_settings", lambda: type("S", (), {"protected_vmids": {118}})())


@pytest.mark.parametrize("body", [{"protection": False}, {"clear": ["protection"]}])
def test_a_container_protected_by_kaji_cannot_lose_its_protection_even_confirmed(api, protected, body):
    c, cid = api
    STATE["cfg"] = cfg(protection=1)
    r = patch(c, cid, **body, confirm=True)
    assert r.status_code == 409 and "protégé par Kaji" in r.json()["detail"] and writes() == []


def test_a_container_protected_by_kaji_still_accepts_harmless_settings(api, protected):
    c, cid = api
    assert patch(c, cid, onboot=True).status_code == 200 and patch(c, cid, features={"nesting": True}).status_code == 200


def test_the_kaji_protection_does_not_apply_to_other_machines(api, monkeypatch):
    c, cid = api
    monkeypatch.setattr("app.routers.options.get_settings", lambda: type("S", (), {"protected_vmids": {116}})())
    STATE["cfg"] = cfg(protection=1)
    assert patch(c, cid, protection=False, confirm=True).status_code == 200


# ============================== erreurs et audit ===================================================================

def test_root_only_setting_refused_by_proxmox_is_translated_without_leak(api):
    """Un réglage réservé à root@pam (par exemple `mount` sur un conteneur non privilégié) : 403 de Proxmox, traduit, sans fuite."""
    c, cid = api
    STATE["fail"] = ("PUT", "/nodes/enzo/lxc/118/config", 403)
    r = patch(c, cid, onboot=True)                                    # 403 sans keyctl/fuse/mount : reste un 502 générique
    assert r.status_code == 502 and SECRET not in r.text and "10.0.0.5" not in r.text
    assert (audit(c)[-1]["action"], audit(c)[-1]["status"]) == ("options", "error") and SECRET not in c.get("/api/audit").text


ROOT_MSG = ("Proxmox réserve keyctl, fuse et mount à root@pam : le token de Kaji ne peut pas les modifier. "
            "Fais-le dans l'interface de Proxmox.")


@pytest.mark.parametrize("features", [{"keyctl": True}, {"fuse": True}, {"fuse": False}, {"mount": ["nfs"]}, {"nesting": True, "keyctl": True}])
def test_root_only_features_give_explicit_403_and_audit(api, features):
    c, cid = api
    STATE["root_only"] = True
    r = patch(c, cid, features=features)
    assert r.status_code == 403 and r.json()["detail"] == ROOT_MSG
    assert SECRET not in r.text and "10.0.0.5" not in r.text and "Permission check" not in r.text
    last = audit(c)[0]
    assert (last["action"], last["status"], last["detail"]) == ("options", "error", ROOT_MSG)


def test_root_only_refusal_is_for_the_whole_request(api):
    """Écriture combinée : Proxmox refuse tout ; Kaji ne prétend rien d'appliqué (une seule écriture tentée, 403)."""
    c, cid = api
    STATE["root_only"] = True
    r = patch(c, cid, onboot=True, timezone="Europe/Paris", features={"keyctl": True})
    assert r.status_code == 403 and len(writes()) == 1


def test_nesting_and_other_writes_still_pass_when_root_only_is_enforced(api):
    c, cid = api
    STATE["root_only"] = True
    assert patch(c, cid, features={"nesting": True}).status_code == 200
    assert patch(c, cid, onboot=True, timezone="Europe/Paris", tty=2, cmode="shell", protection=False).status_code == 200


def test_root_only_message_only_when_proxmox_refused(api):
    """Sans refus de Proxmox, une demande avec keyctl passe : le message n'est pas posé d'avance."""
    c, cid = api
    assert patch(c, cid, features={"keyctl": True}).status_code == 200


def test_other_proxmox_errors_on_root_only_request_stay_502(api):
    c, cid = api
    STATE["fail"] = ("PUT", "/nodes/enzo/lxc/118/config", 500)
    r = patch(c, cid, features={"keyctl": True})
    assert r.status_code == 502 and r.json()["detail"] != ROOT_MSG


def test_403_on_read_with_root_only_request_is_not_the_root_only_message(api):
    """Le message n'est posé que pour le refus de l'ÉCRITURE : un 403 en lecture reste générique."""
    c, cid = api
    STATE["fail"] = ("GET", "/nodes/enzo/lxc/118/config", 403)
    r = patch(c, cid, features={"keyctl": True})
    assert r.status_code == 502 and r.json()["detail"] != ROOT_MSG and writes() == []


def test_403_on_nesting_only_request_is_not_the_root_only_message(api):
    """`nesting` est permis au token : un 403 sur cette seule demande a une autre cause, root@pam ne l'explique pas."""
    c, cid = api
    STATE["fail"] = ("PUT", "/nodes/enzo/lxc/118/config", 403)
    r = patch(c, cid, features={"nesting": True})
    assert r.status_code == 502 and r.json()["detail"] != ROOT_MSG


def test_nesting_alone_on_container_that_already_has_keyctl_gives_root_only_message(api):
    """Kaji renvoie toute la chaîne `features` (nesting=0,keyctl=1) : si Proxmox refuse, la cause est expliquée."""
    c, cid = api
    STATE["root_only"] = True
    STATE["cfg"] = {**CFG0, "features": "nesting=1,keyctl=1"}
    r = patch(c, cid, features={"nesting": False})
    assert r.status_code == 403 and r.json()["detail"] == ROOT_MSG
    assert "keyctl=1" in writes()[0]["form"]["features"]


def test_clear_features_on_container_with_root_only_flags_gives_root_only_message(api):
    c, cid = api
    STATE["root_only"] = True
    STATE["cfg"] = {**CFG0, "features": "nesting=1,fuse=1"}
    r = patch(c, cid, clear=["features"])
    assert r.status_code == 403 and r.json()["detail"] == ROOT_MSG


def test_clear_features_without_root_only_flags_is_not_explained_by_root(api):
    c, cid = api
    STATE["root_only"] = True
    STATE["cfg"] = {**CFG0, "features": "nesting=1"}
    assert patch(c, cid, clear=["features"]).status_code == 200
    STATE["fail"] = ("PUT", "/nodes/enzo/lxc/118/config", 403)
    r = patch(c, cid, clear=["features"])
    assert r.status_code == 502 and r.json()["detail"] != ROOT_MSG


def test_root_only_features_remain_readable(api):
    c, cid = api
    STATE["cfg"] = {**CFG0, "features": "nesting=1,keyctl=1,fuse=1,mount=nfs"}
    f = c.get(u(cid)).json()["options"]["features"]
    assert f == {"nesting": True, "fuse": True, "keyctl": True, "mount": ["nfs"]}


def test_unreadable_config_is_502_and_nothing_is_written(api):
    c, cid = api
    STATE["cfg"] = ["pas", "un", "dict"]
    assert patch(c, cid, onboot=True).status_code == 502 and writes() == []


def test_audit_records_success_every_refusal_and_error(api):
    c, cid = api
    patch(c, cid, onboot=True, description="mot de passe : secret-de-test")            # succès
    patch(c, cid)                                                                      # rien à faire
    patch(c, cid, tty=2, clear=["tty"])                                                # conflit
    STATE["cfg"] = cfg(protection=1)
    patch(c, cid, protection=False)                                                    # confirmation requise
    STATE["fail"] = ("PUT", "/nodes/enzo/lxc/118/config", 500)
    patch(c, cid, console=False)                                                       # erreur Proxmox
    log = audit(c)
    assert [(e["action"], e["status"], e["target"]) for e in log] == [("options", s, "lxc/118@enzo") for s in ("started", "error", "error", "error", "error")]
    assert "onboot=1" in log[0]["detail"] and "description" in log[0]["detail"] and "secret-de-test" not in c.get("/api/audit").text
    assert "Confirmation requise" in log[3]["detail"]
