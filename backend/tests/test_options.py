"""Options d'une VM (onglet « Options ») : faux Proxmox STRICT. RIEN n'a tourné sur un vrai cluster.

Le faux n'accepte, sur `PUT …/qemu/{vmid}/config`, que les paramètres du schéma réel lu par PC A (ticket #144) : tout autre paramètre
répond 400. Chaque garde-fou est testé séparément ; un refus ne déclenche aucune écriture.
"""
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
# Schéma réel de `PUT /nodes/{node}/qemu/{vmid}/config` (extrait du ticket) : tout le reste → 400.
ALLOWED = {"acpi", "agent", "delete", "description", "digest", "freeze", "hookscript", "hotplug", "keyboard", "kvm", "localtime", "lock", "name", "numa",
           "onboot", "ostype", "protection", "reboot", "revert", "startup", "tablet", "tags", "vga"}
CFG0 = {"name": "kaji-sandbox", "memory": 256, "digest": DIGEST, "hookscript": "local:snippets/h.pl", "args": "-evil", "lock": "backup",
        "scsi0": "local-lvm:vm-115-disk-0,size=1G"}
CALLS: list[dict] = []
STATE: dict = {}


def _json(code, body, reason="OK"):
    return httpx.Response(code, json=body, extensions={"reason_phrase": reason.encode()})


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()} if request.content else {}
    CALLS.append({"method": request.method, "path": p, "params": dict(request.url.params), "form": form})
    if STATE.get("fail") == (request.method, p):
        return _json(500, {"data": None})
    if request.method == "GET" and p == "/nodes/enzo/qemu/115/config":
        return _json(200, {"data": STATE.get("cfg", CFG0)})
    if request.method == "GET" and p == "/nodes/enzo/qemu/115/pending":
        return _json(200, {"data": STATE.get("pending", [])})
    if request.method == "PUT" and p == "/nodes/enzo/qemu/115/config":
        bad = set(form) - ALLOWED
        return _json(400, {"data": None}) if bad else _json(200, {"data": None})
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


def u(cid, vmid=115, node="enzo"):
    return f"/api/connections/{cid}/guests/{node}/qemu/{vmid}/options"


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
    assert client.get("/api/connections/1/guests/enzo/qemu/115/options").status_code == 401
    assert client.patch("/api/connections/1/guests/enzo/qemu/115/options", json={"onboot": True}).status_code == 401


def test_unknown_connection(api):
    c, _ = api
    assert c.get(u(999)).status_code == 404 and c.patch(u(999), json={"onboot": True}).status_code == 404 and CALLS == []


@pytest.mark.parametrize("vmid,node", [(99, "enzo"), (0, "enzo"), (1000000000, "enzo"), ("x", "enzo"), (115, "a;b"), (115, "-x")])
def test_invalid_path_is_refused_and_nothing_is_called(api, vmid, node):
    c, cid = api
    assert c.get(u(cid, vmid, node)).status_code in (404, 422) and c.patch(u(cid, vmid, node), json={"onboot": True}).status_code in (404, 422)
    assert CALLS == []


@pytest.mark.parametrize("method", ["put", "post", "delete"])
def test_no_other_verb(api, method):
    c, cid = api
    # POST tombe sur la route générique des actions (« options » n'est pas une action : 422) ; dans tous les cas rien n'est écrit.
    assert getattr(c, method)(u(cid)).status_code in (404, 405, 422) and CALLS == []


# ============================== lecture ============================================================================

def test_get_reads_config_then_pending_and_shapes_every_field(api):
    c, cid = api
    STATE["cfg"] = cfg(onboot=1, startup="order=2,up=30,down=60", ostype="l26", agent="enabled=1,fstrim_cloned_disks=1,type=virtio", tablet=0,
                       protection=1, hotplug="network,disk,usb", numa=1, localtime=0, acpi=1, kvm=0, freeze=0, description="une VM\nde test")
    STATE["pending"] = [{"key": "onboot", "value": 1, "pending": 0}, {"key": "memory", "value": 256, "pending": 512}, {"key": "tablet", "delete": 1}]
    r = c.get(u(cid))
    assert r.status_code == 200
    d = r.json()
    assert [(x["method"], x["path"], x["params"]) for x in CALLS] == [("GET", "/nodes/enzo/qemu/115/config", {"current": "1"}), ("GET", "/nodes/enzo/qemu/115/pending", {})]
    o = d["options"]
    assert (o["onboot"], o["tablet"], o["protection"], o["numa"], o["localtime"], o["acpi"], o["kvm"], o["freeze"]) == (True, False, True, True, False, True, False, False)
    assert o["startup"] == {"order": 2, "up": 30, "down": 60} and o["ostype"] == "l26" and o["hotplug"] == ["disk", "network", "usb"]
    assert o["agent"] == {"enabled": True, "fstrim_cloned_disks": True} and o["description"] == "une VM\nde test"
    assert d["pending"] == [{"key": "onboot", "value": 1, "pending": 0, "delete": False}, {"key": "tablet", "value": None, "pending": None, "delete": True}]
    assert d["reboot_required"] is True and d["type"] == "qemu"


def test_get_absent_settings_are_none_and_unmanaged_keys_are_never_shown(api):
    c, cid = api
    d = c.get(u(cid)).json()
    assert all(v is None for v in d["options"].values()) and d["pending"] == [] and d["reboot_required"] is False
    assert "hookscript" not in c.get(u(cid)).text and "-evil" not in c.get(u(cid)).text and "backup" not in c.get(u(cid)).text


@pytest.mark.parametrize("raw,expected", [("1", {"enabled": True, "fstrim_cloned_disks": None}), ("0", {"enabled": False, "fstrim_cloned_disks": None}),
                                          ("enabled=0,type=isa", {"enabled": False, "fstrim_cloned_disks": None}),
                                          ("1,fstrim_cloned_disks=0", {"enabled": True, "fstrim_cloned_disks": False})])
def test_get_agent_forms(api, raw, expected):
    c, cid = api
    STATE["cfg"] = cfg(agent=raw)
    assert c.get(u(cid)).json()["options"]["agent"] == expected


@pytest.mark.parametrize("raw,expected", [("0", []), ("1", ["disk", "network", "usb"]), ("cpu,memory,evil", ["cpu", "memory"])])
def test_get_hotplug_forms(api, raw, expected):
    c, cid = api
    STATE["cfg"] = cfg(hotplug=raw)
    assert c.get(u(cid)).json()["options"]["hotplug"] == expected


def test_get_tolerates_garbage_values(api):
    c, cid = api
    STATE["cfg"] = cfg(onboot="peut-être", startup="order=x,up=,down=-1", ostype="../x", description=12, agent="???", hotplug=5)
    o = c.get(u(cid)).json()["options"]
    assert o["onboot"] is None and o["startup"] == {"order": None, "up": None, "down": None} and o["ostype"] is None and o["description"] is None


def test_get_proxmox_error_is_502(api):
    c, cid = api
    STATE["fail"] = ("GET", "/nodes/enzo/qemu/115/config")
    assert c.get(u(cid)).status_code == 502


# ============================== écriture : paramètres exacts =======================================================

@pytest.mark.parametrize("body,form", [
    ({"onboot": True}, {"onboot": "1"}), ({"onboot": False}, {"onboot": "0"}), ({"tablet": False}, {"tablet": "0"}), ({"numa": True}, {"numa": "1"}),
    ({"localtime": True}, {"localtime": "1"}), ({"protection": True}, {"protection": "1"}), ({"ostype": "win11"}, {"ostype": "win11"}),
    ({"kvm": True}, {"kvm": "1"}), ({"acpi": True}, {"acpi": "1"}), ({"freeze": False}, {"freeze": "0"}),
    ({"description": "ligne 1\nligne 2"}, {"description": "ligne 1\nligne 2"}),
    ({"hotplug": ["usb", "disk", "network"]}, {"hotplug": "disk,network,usb"}), ({"hotplug": []}, {"hotplug": "0"}),
    ({"startup": {"order": 1, "up": 30, "down": 60}}, {"startup": "order=1,up=30,down=60"}), ({"startup": {"order": 0}}, {"startup": "order=0"}),
    ({"agent": {"enabled": True}}, {"agent": "enabled=1"}), ({"agent": {"enabled": True, "fstrim_cloned_disks": True}}, {"agent": "enabled=1,fstrim_cloned_disks=1"}),
])
def test_patch_sends_exact_params_with_the_digest(api, body, form):
    c, cid = api
    r = patch(c, cid, **body)
    assert r.status_code == 200 and r.json()["changed"] == sorted(form) and r.json()["removed"] == []
    assert len(writes()) == 1 and writes()[0]["method"] == "PUT" and writes()[0]["path"] == "/nodes/enzo/qemu/115/config"
    assert writes()[0]["form"] == {**form, "digest": DIGEST}


def test_patch_without_a_valid_digest_sends_none(api):
    c, cid = api
    for d in (None, "xyz", "A" * 40, "a" * 39):
        STATE["cfg"] = {k: v for k, v in cfg(digest=d).items() if d is not None or k != "digest"}
        CALLS.clear()
        assert patch(c, cid, onboot=True).status_code == 200 and "digest" not in writes()[0]["form"]


def test_startup_keeps_the_values_that_are_not_changed(api):
    c, cid = api
    STATE["cfg"] = cfg(startup="order=2,up=30,down=60")
    patch(c, cid, startup={"up": 45})
    assert writes()[0]["form"]["startup"] == "order=2,up=45,down=60"


def test_agent_keeps_the_properties_kaji_does_not_manage(api):
    c, cid = api
    STATE["cfg"] = cfg(agent="enabled=1,type=isa,freeze-fs-on-backup=0")
    patch(c, cid, agent={"fstrim_cloned_disks": True})
    assert writes()[0]["form"]["agent"] == "enabled=1,fstrim_cloned_disks=1,type=isa,freeze-fs-on-backup=0"


def test_agent_short_form_is_converted_not_lost(api):
    c, cid = api
    STATE["cfg"] = cfg(agent="1")
    patch(c, cid, agent={"fstrim_cloned_disks": False})
    assert writes()[0]["form"]["agent"] == "enabled=1,fstrim_cloned_disks=0"


def test_an_unreadable_agent_property_refuses_the_change_instead_of_dropping_it(api):
    c, cid = api
    STATE["cfg"] = cfg(agent="enabled=1,type=is a;evil")
    r = patch(c, cid, agent={"enabled": False})
    assert r.status_code == 422 and writes() == []


def test_several_changes_in_one_write(api):
    c, cid = api
    r = patch(c, cid, onboot=True, ostype="l26", tablet=False)
    assert r.json()["changed"] == ["onboot", "ostype", "tablet"] and len(writes()) == 1


# ============================== retrait (delete) ===================================================================

def test_clear_goes_in_one_delete_parameter_in_the_given_order(api):
    c, cid = api
    r = patch(c, cid, clear=["onboot", "tablet", "description"])
    assert r.json() == {"changed": [], "removed": ["onboot", "tablet", "description"]}
    assert writes()[0]["form"] == {"delete": "onboot,tablet,description", "digest": DIGEST}


def test_clear_and_set_together_for_different_settings(api):
    c, cid = api
    patch(c, cid, ostype="l26", clear=["onboot"])
    assert writes()[0]["form"] == {"ostype": "l26", "delete": "onboot", "digest": DIGEST}


def test_clear_duplicates_are_collapsed(api):
    c, cid = api
    patch(c, cid, clear=["onboot", "onboot"])
    assert writes()[0]["form"]["delete"] == "onboot"


def test_a_setting_cannot_be_set_and_cleared_at_once(api):
    c, cid = api
    r = patch(c, cid, onboot=True, clear=["onboot"])
    assert r.status_code == 422 and writes() == []


@pytest.mark.parametrize("key", ["hookscript", "args", "lock", "vmgenid", "name", "memory", "digest", "delete", "scsi0", "net0", "../x", "onboot,tablet", ""])
def test_clear_only_accepts_the_whitelist(api, key):
    c, cid = api
    assert patch(c, cid, clear=[key]).status_code == 422 and CALLS == []


# ============================== validation =========================================================================

@pytest.mark.parametrize("body", [
    {"onboot": "yes"}, {"onboot": 1}, {"onboot": "true"}, {"onboot": None, "protection": "0"}, {"tablet": 0}, {"kvm": "1"},
    {"ostype": "../x"}, {"ostype": "windows"}, {"ostype": ""}, {"ostype": "l26,evil=1"},
    {"startup": {}}, {"startup": {"order": -1}}, {"startup": {"order": 10000}}, {"startup": {"up": 86401}}, {"startup": {"down": -5}},
    {"startup": {"order": "x"}}, {"startup": {"order": 1.5}}, {"startup": "order=1"},
    {"agent": {}}, {"agent": {"enabled": "1"}}, {"agent": {"enabled": 1}}, {"agent": "enabled=1"}, {"agent": {"type": "isa"}},
    {"hotplug": ["evil"]}, {"hotplug": ["disk", "disk"]}, {"hotplug": "disk,network"}, {"hotplug": ["disk,network"]}, {"hotplug": ["disk"] * 7},
    {"description": "x" * 8193}, {"description": "a\x00b"}, {"description": "a\x1bb"}, {"description": 12},
    {"confirm": "true"}, {"confirm": 1}, {"confirm": "oui", "onboot": True},
    {"clear": "onboot"}, {"clear": [1]},
])
def test_invalid_values_are_refused_and_nothing_is_called(api, body):
    c, cid = api
    assert patch(c, cid, **body).status_code == 422 and CALLS == []


def test_the_validation_error_does_not_echo_the_value(api):
    c, cid = api
    r = patch(c, cid, ostype=SECRET)
    assert r.status_code == 422 and SECRET not in r.text


def test_empty_patch_is_400_and_calls_nothing(api):
    c, cid = api
    assert patch(c, cid).status_code == 400 and patch(c, cid, confirm=True).status_code == 400 and CALLS == []


@pytest.mark.parametrize("extra", [{"hookscript": "local:snippets/x.pl"}, {"args": "-evil"}, {"lock": "backup"}, {"vmgenid": "x"}, {"name": "autre"}, {"memory": 99999},
                                   {"delete": "scsi0"}, {"digest": "b" * 40}, {"revert": "memory"}, {"tags": "x"}, {"net0": "virtio"}, {"node": "pve9"}])
def test_unknown_fields_are_ignored_and_never_forwarded(api, extra):
    c, cid = api
    assert patch(c, cid, onboot=True, **extra).status_code == 200
    assert writes()[0]["form"] == {"onboot": "1", "digest": DIGEST}


def test_only_unknown_fields_means_no_change(api):
    c, cid = api
    assert patch(c, cid, hookscript="x", args="-evil").status_code == 400 and CALLS == []


# ============================== risques et confirmation ============================================================

@pytest.mark.parametrize("body,current,word", [
    ({"protection": False}, {"protection": 1}, "protection"), ({"clear": ["protection"]}, {"protection": 1}, "protection"),
    ({"kvm": False}, {}, "kvm=0"), ({"kvm": False}, {"kvm": 1}, "kvm=0"), ({"acpi": False}, {}, "acpi=0"), ({"freeze": True}, {}, "freeze=1"),
])
def test_dangerous_settings_need_a_server_side_confirmation_and_write_nothing(api, body, current, word):
    c, cid = api
    STATE["cfg"] = cfg(**current)
    r = patch(c, cid, **body)
    assert is_confirmation(r) and word in r.json()["detail"] and writes() == []
    assert patch(c, cid, **body, confirm=True).status_code == 200 and len(writes()) == 1


@pytest.mark.parametrize("body,current", [
    ({"protection": True}, {}), ({"protection": False}, {}), ({"protection": False}, {"protection": 0}), ({"clear": ["protection"]}, {}),
    ({"clear": ["protection"]}, {"protection": 0}), ({"kvm": True}, {}), ({"kvm": False}, {"kvm": 0}), ({"acpi": True}, {}), ({"acpi": False}, {"acpi": 0}),
    ({"freeze": False}, {}), ({"freeze": True}, {"freeze": 1}), ({"clear": ["kvm", "acpi", "freeze"]}, {"kvm": 0, "acpi": 0, "freeze": 1}), ({"onboot": False}, {}),
])
def test_safe_or_unchanged_settings_need_no_confirmation(api, body, current):
    c, cid = api
    STATE["cfg"] = cfg(**current)
    assert patch(c, cid, **body).status_code == 200


def test_the_risk_comes_from_the_state_read_at_proxmox_not_from_the_request(api):
    """Lever la protection d'une machine DÉJÀ non protégée n'est pas un risque ; d'une machine protégée, si."""
    c, cid = api
    assert patch(c, cid, protection=False).status_code == 200
    STATE["cfg"] = cfg(protection="1")
    assert is_confirmation(patch(c, cid, protection=False))


def test_all_reasons_are_listed_together(api):
    c, cid = api
    STATE["cfg"] = cfg(protection=1)
    d = patch(c, cid, protection=False, kvm=False, acpi=False, freeze=True).json()["detail"]
    assert all(w in d for w in ("protection", "kvm=0", "acpi=0", "freeze=1")) and d.count(" ; ") == 3


def test_confirm_is_never_forwarded_to_proxmox(api):
    c, cid = api
    patch(c, cid, kvm=False, confirm=True)
    assert "confirm" not in writes()[0]["form"] and "confirm" not in writes()[0]["params"]


def test_the_confirmation_is_requested_before_any_write_but_after_validation(api):
    c, cid = api
    assert patch(c, cid, kvm=False, ostype="../x").status_code == 422 and CALLS == []


# ============================== protection de Kaji (KAJI_PROTECTED_VMIDS) ==========================================

@pytest.fixture
def protected(monkeypatch):
    monkeypatch.setattr("app.routers.options.get_settings", lambda: type("S", (), {"protected_vmids": {115}})())


@pytest.mark.parametrize("body,current", [
    ({"protection": False}, {"protection": 1}), ({"clear": ["protection"]}, {"protection": 1}), ({"kvm": False}, {}), ({"acpi": False}, {}), ({"freeze": True}, {}),
])
def test_a_machine_protected_by_kaji_refuses_dangerous_settings_even_confirmed(api, protected, body, current):
    c, cid = api
    STATE["cfg"] = cfg(**current)
    r = patch(c, cid, **body, confirm=True)
    assert r.status_code == 409 and "protégée par Kaji" in r.json()["detail"] and writes() == []


def test_a_machine_protected_by_kaji_still_accepts_harmless_settings(api, protected):
    c, cid = api
    assert patch(c, cid, onboot=True).status_code == 200 and patch(c, cid, protection=True).status_code == 200


def test_the_kaji_protection_does_not_apply_to_other_machines(api, monkeypatch):
    c, cid = api
    monkeypatch.setattr("app.routers.options.get_settings", lambda: type("S", (), {"protected_vmids": {116}})())
    assert patch(c, cid, kvm=False, confirm=True).status_code == 200


# ============================== erreurs et audit ===================================================================

def test_unreadable_config_is_502_and_nothing_is_written(api):
    c, cid = api
    STATE["cfg"] = ["pas", "un", "dict"]
    assert patch(c, cid, onboot=True).status_code == 502 and writes() == []
    assert audit(c)[-1]["status"] == "error"


def test_proxmox_write_error_is_502_audited_without_the_secret(api):
    c, cid = api
    STATE["fail"] = ("PUT", "/nodes/enzo/qemu/115/config")
    r = patch(c, cid, onboot=True)
    assert r.status_code == 502 and SECRET not in r.text
    assert (audit(c)[-1]["action"], audit(c)[-1]["status"]) == ("options", "error") and SECRET not in c.get("/api/audit").text


def test_audit_records_success_every_refusal_and_error(api):
    c, cid = api
    patch(c, cid, onboot=True, description="mot de passe : secret-de-test")            # succès
    patch(c, cid, kvm=False)                                                           # confirmation requise
    patch(c, cid)                                                                      # rien à faire
    patch(c, cid, onboot=True, clear=["onboot"])                                       # conflit
    STATE["fail"] = ("PUT", "/nodes/enzo/qemu/115/config")
    patch(c, cid, tablet=False)                                                        # erreur Proxmox
    log = audit(c)
    assert [(e["action"], e["status"], e["target"]) for e in log] == [("options", s, "qemu/115@enzo") for s in ("started", "error", "error", "error", "error")]
    assert "onboot=1" in log[0]["detail"] and "description" in log[0]["detail"] and "secret-de-test" not in c.get("/api/audit").text
    assert "Confirmation requise" in log[1]["detail"]
