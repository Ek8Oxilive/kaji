"""Options fines d'un disque, d'une carte réseau et du CPU (lot #377) : faux Proxmox STRICT qui APPLIQUE la configuration.

Noms, énumérations et bornes : schéma réel de Proxmox 9 (`apidoc.js`). Le faux refuse (400) toute option hors schéma, applique `delete=` et
vérifie le `digest`. Chaque garde-fou est testé séparément ; un refus ne déclenche aucune écriture. RIEN n'a encore tourné sur le vrai cluster.
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
DISK_OK = {"aio": ("native", "threads", "io_uring"), "cache": ("none", "writethrough", "writeback", "unsafe", "directsync"), "discard": ("ignore", "on")}
DISK_BOOL = {"backup", "iothread", "ssd", "ro", "replicate", "detect_zeroes", "snapshot", "shared", "scsiblock"}
DISK_NUM = {"mbps", "mbps_rd", "mbps_wr", "iops", "iops_rd", "iops_wr", "size", "media", "format", "serial"}
NET_OK = {"bridge", "firewall", "link_down", "macaddr", "mtu", "queues", "rate", "tag", "trunks", "virtio", "e1000", "rtl8139", "vmxnet3", "hwaddr", "name", "type", "ip", "gw"}
CPU_OK = {"cpuunits", "cpulimit", "affinity", "hugepages", "digest", "delete"}
CALLS: list[dict] = []
ST: dict = {}


def fresh():
    ST.clear()
    ST["cfgs"] = {
        ("qemu", 115): {"name": "kaji-sandbox", "scsihw": "virtio-scsi-single", "digest": DIGEST, "cores": 2,
                        "scsi0": "local-lvm:vm-115-disk-0,size=32G,discard=on", "virtio1": "local-lvm:vm-115-disk-1,size=8G,cache=none",
                        "sata0": "local-lvm:vm-115-disk-2,size=4G", "ide0": "local-lvm:vm-115-disk-3,size=2G", "ide2": "none,media=cdrom",
                        "scsi1": "local-lvm:vm-115-cloudinit,media=cdrom", "ide3": "local-lvm:vm-115-cloudinit,size=4M", "net0": "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,firewall=1,tag=10",
                        "net1": "e1000=AA:BB:CC:DD:EE:00,bridge=vmbr0"},
        ("lxc", 120): {"hostname": "ct", "digest": DIGEST, "net0": "name=eth0,bridge=vmbr0,hwaddr=AA:BB:CC:DD:EE:11,type=veth,ip=dhcp"},
    }
    ST["cpus"] = 12


def _json(code, body, reason="OK"):
    return httpx.Response(code, json=body, extensions={"reason_phrase": reason.encode()})


def _check_opts(key: str, value: str):
    head, *rest = value.split(",")
    for part in rest:
        k, _, v = part.partition("=")
        if key.startswith("net"):
            if k not in NET_OK:
                return f"option de carte inconnue {k}"
            if k == "mtu" and not (v.isdigit() and 1 <= int(v) <= 65535):
                return "mtu"
            if k == "queues" and not (v.isdigit() and int(v) <= 64):
                return "queues"
            if k in ("link_down", "firewall") and v not in ("0", "1"):
                return k
        else:
            if k in DISK_OK and v not in DISK_OK[k]:
                return f"{k}={v}"
            if k in DISK_BOOL and v not in ("0", "1"):
                return f"{k}={v}"
            if k not in DISK_OK and k not in DISK_BOOL and k not in DISK_NUM:
                return f"option de disque inconnue {k}"
    return None


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()} if request.content else {}
    CALLS.append({"method": request.method, "path": p, "form": form})
    parts = p.strip("/").split("/")
    if request.method == "GET" and p == "/nodes/enzo/status":
        if ST.get("status_down"):
            return _json(500, {"data": None})
        return _json(200, {"data": {"cpuinfo": {"cpus": ST["cpus"]}}})
    if request.method == "GET" and len(parts) == 5 and parts[:2] == ["nodes", "enzo"] and parts[4] == "pending":
        return _json(200, {"data": []})
    if len(parts) == 5 and parts[:2] == ["nodes", "enzo"] and parts[4] == "config":
        cfg = ST["cfgs"].get((parts[2], int(parts[3])))
        if cfg is None:
            return _json(404, {"data": None})
        if request.method == "GET":
            return _json(200, {"data": cfg})
        if ST.get("race"):
            ST["n"] = ST.get("n", 0) + 1
            cfg["digest"] = str(ST["n"]).zfill(40)                # quelqu'un d'autre a modifié la configuration entre notre lecture et notre écriture
        if form.get("digest") not in (None, cfg["digest"]):
            return _json(400, {"data": None}, "digest mismatch")
        for k, v in form.items():
            if k in ("digest", "delete"):
                continue
            if parts[2] == "qemu" and (k.startswith(("scsi", "virtio", "sata", "ide", "net")) or k in CPU_OK):
                if k in CPU_OK:
                    if k == "cpuunits" and not (1 <= int(v) <= 262144):
                        return _json(400, {"data": None}, "cpuunits")
                    if k == "hugepages" and v not in ("any", "2", "1024"):
                        return _json(400, {"data": None}, "hugepages")
                else:
                    if k not in cfg:
                        return _json(400, {"data": None}, "périphérique inexistant")
                    msg = _check_opts(k, v)
                    if msg:
                        return _json(400, {"data": None}, msg)
            elif parts[2] == "lxc" and k.startswith("net"):
                msg = _check_opts(k, v)
                if msg:
                    return _json(400, {"data": None}, msg)
            else:
                return _json(400, {"data": None}, f"paramètre inconnu {k}")
        if ST.get("noapply"):
            return _json(200, {"data": None})                  # Proxmox répond OK mais n'écrit rien
        for k, v in form.items():
            if k not in ("digest", "delete"):
                cfg[k] = str(float(v)) if ST.get("float_echo") and k == "cpulimit" else v
        for k in [x for x in form.get("delete", "").split(",") if x]:
            cfg.pop(k, None)
        return _json(200, {"data": None})
    return _json(404, {"data": None})


@pytest.fixture
def api(client):
    CALLS.clear()
    fresh()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    CALLS.clear()
    yield client, cid
    app.dependency_overrides.clear()


@pytest.fixture
def protected(monkeypatch):
    monkeypatch.setattr("app.routers.hw_options.get_settings", lambda: type("S", (), {"protected_vmids": {115, 120}})())


def disk(c, cid, key, **b):
    return c.patch(f"/api/connections/{cid}/guests/enzo/qemu/115/disks/{key}/options", json=b)


def net(c, cid, key, gtype="qemu", vmid=115, **b):
    return c.patch(f"/api/connections/{cid}/guests/enzo/{gtype}/{vmid}/nets/{key}/options", json=b)


def cpu(c, cid, **b):
    return c.patch(f"/api/connections/{cid}/guests/enzo/qemu/115/cpu-options", json=b)


def puts():
    return [x for x in CALLS if x["method"] == "PUT"]


def cfg(gtype="qemu", vmid=115):
    return ST["cfgs"][(gtype, vmid)]


# ------------------------------------------------------------------ disque
def test_disk_options_are_written_in_the_existing_string_and_everything_else_is_kept(api):
    c, cid = api
    r = disk(c, cid, "scsi0", cache="none", iothread=True, ssd=True, mbps_rd=100, iops_wr=500)
    assert r.status_code == 200, r.text
    assert cfg()["scsi0"] == "local-lvm:vm-115-disk-0,size=32G,discard=on,cache=none,iothread=1,ssd=1,mbps_rd=100,iops_wr=500"
    assert puts()[0]["form"]["digest"] == DIGEST and set(puts()[0]["form"]) == {"scsi0", "digest"}


def test_disk_option_is_replaced_in_place_and_cleared(api):
    c, cid = api
    assert disk(c, cid, "scsi0", discard="ignore").status_code == 200
    assert cfg()["scsi0"] == "local-lvm:vm-115-disk-0,size=32G,discard=ignore"
    assert disk(c, cid, "scsi0", clear=["discard"]).status_code == 200
    assert cfg()["scsi0"] == "local-lvm:vm-115-disk-0,size=32G"


def test_a_replaced_option_keeps_its_position_in_the_middle_of_the_string(api):
    c, cid = api
    assert disk(c, cid, "scsi0", cache="none").status_code == 200
    assert disk(c, cid, "scsi0", discard="ignore").status_code == 200
    assert cfg()["scsi0"] == "local-lvm:vm-115-disk-0,size=32G,discard=ignore,cache=none"


def test_float_limit_is_written_without_trailing_zero(api):
    c, cid = api
    assert disk(c, cid, "scsi0", mbps_wr=12.5, mbps_rd=100.0).status_code == 200
    assert cfg()["scsi0"].endswith("mbps_rd=100,mbps_wr=12.5")


@pytest.mark.parametrize("key,body,code", [
    ("ide2", {"cache": "none"}, 422), ("scsi1", {"cache": "none"}, 422), ("ide3", {"cache": "none"}, 422),   # CD/DVD, cloud-init (avec ou sans media=cdrom)
    ("scsi9", {"cache": "none"}, 404),
    ("virtio1", {"ssd": True}, 422),                                                           # pas de ssd sur virtio
    ("ide0", {"iothread": True}, 422), ("sata0", {"iothread": True}, 422),                     # iothread : virtio ou scsi-single
    ("scsi0", {"mbps": 10, "mbps_rd": 5}, 422), ("scsi0", {"iops": 10, "iops_wr": 5}, 422),
    ("scsi0", {"cache": "none", "clear": ["cache"]}, 422), ("scsi0", {}, 422), ("scsi0", {"clear": []}, 422),
    ("scsi0", {"cache": "turbo"}, 422), ("scsi0", {"discard": "yes"}, 422), ("scsi0", {"aio": "x"}, 422),
    ("scsi0", {"ssd": "1"}, 422), ("scsi0", {"ssd": 1}, 422), ("scsi0", {"iothread": "true"}, 422),
    ("scsi0", {"mbps_rd": -1}, 422), ("scsi0", {"mbps_rd": "10"}, 422), ("scsi0", {"mbps_rd": True}, 422), ("scsi0", {"iops": 1.5}, 422),
    ("scsi0", {"iops": 10**9}, 422), ("scsi0", {"clear": ["size"]}, 422), ("scsi0", {"clear": ["media"]}, 422),
])
def test_disk_refusals_write_nothing(api, key, body, code):
    c, cid = api
    assert disk(c, cid, key, **body).status_code == code
    assert not puts()


def test_iothread_on_scsi_needs_the_single_controller(api):
    c, cid = api
    cfg()["scsihw"] = "virtio-scsi-pci"
    assert disk(c, cid, "scsi0", iothread=True).status_code == 422 and not puts()
    cfg()["scsihw"] = "virtio-scsi-single"
    assert disk(c, cid, "scsi0", iothread=True).status_code == 200
    assert disk(c, cid, "virtio1", iothread=True).status_code == 200                           # virtio : toujours permis


def test_unknown_fields_are_ignored_never_forwarded(api):
    c, cid = api
    assert disk(c, cid, "scsi0", cache="none", file="/etc/passwd", serial="x\ny", size="1T").status_code == 200
    assert cfg()["scsi0"] == "local-lvm:vm-115-disk-0,size=32G,discard=on,cache=none"


@pytest.mark.parametrize("body,why", [({"cache": "unsafe"}, "cache=unsafe"), ({"cache": "writeback"}, "cache=writeback"), ({"backup": False}, "backup=0")])
def test_risky_disk_options_need_confirm_decided_by_the_server(api, body, why):
    c, cid = api
    r = disk(c, cid, "scsi0", **body)
    assert r.status_code == 400 and why in r.json()["detail"] and not puts()
    assert disk(c, cid, "scsi0", confirm=True, **body).status_code == 200 and len(puts()) == 1


def test_harmless_options_never_ask_for_confirmation(api):
    c, cid = api
    assert disk(c, cid, "scsi0", cache="none", discard="on", ssd=True, backup=True, ro=False, replicate=True).status_code == 200


def test_disk_dry_run_writes_nothing_and_shows_the_result_and_risks(api):
    c, cid = api
    r = disk(c, cid, "scsi0", cache="unsafe", dry_run=True)
    assert r.status_code == 200 and r.json()["dry_run"] is True and r.json()["options"]["cache"] == "unsafe" and r.json()["risks"]
    assert not puts() and "volume" not in r.text and "vm-115-disk-0" not in r.text


def test_protected_machine_is_refused_even_confirmed_and_without_any_write(api, protected):
    c, cid = api
    assert disk(c, cid, "scsi0", cache="none").status_code == 409
    assert disk(c, cid, "scsi0", cache="unsafe", confirm=True).status_code == 409
    assert net(c, cid, "net0", rate=5).status_code == 409 and cpu(c, cid, cpuunits=100).status_code == 409
    assert not puts()


def test_dry_run_tells_that_the_machine_is_protected(api, protected):
    c, cid = api
    assert disk(c, cid, "scsi0", cache="none", dry_run=True).json()["protected"] is True and not puts()


def test_silent_non_write_by_proxmox_is_reported_not_hidden(api):
    c, cid = api
    ST["noapply"] = True
    r = disk(c, cid, "scsi0", cache="none")
    assert r.status_code == 502 and "n'a pas enregistré" in r.json()["detail"]


def test_digest_of_the_read_config_is_always_sent_and_a_concurrent_change_is_refused(api):
    c, cid = api
    assert disk(c, cid, "scsi0", cache="none").status_code == 200 and puts()[-1]["form"]["digest"] == DIGEST
    ST["race"] = True
    before = cfg()["scsi0"]
    r = disk(c, cid, "scsi0", discard="ignore")
    assert r.status_code == 502 and cfg()["scsi0"] == before                                   # refusé par Proxmox : rien d'écrit
    assert net(c, cid, "net0", rate=5).status_code == 502 and cpu(c, cid, cpuunits=100).status_code == 502


# ------------------------------------------------------------------ carte réseau
def test_qemu_virtio_net_options(api):
    c, cid = api
    r = net(c, cid, "net0", rate=12.5, mtu=1500, queues=4, trunks=["10", "20-30"])
    assert r.status_code == 200, r.text
    assert cfg()["net0"] == "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,firewall=1,tag=10,rate=12.5,mtu=1500,queues=4,trunks=10;20-30"


def test_net_option_is_replaced_in_place_and_cleared(api):
    c, cid = api
    net(c, cid, "net0", rate=5)
    assert net(c, cid, "net0", rate=8).status_code == 200 and "rate=8" in cfg()["net0"] and "rate=5" not in cfg()["net0"]
    assert net(c, cid, "net0", clear=["rate"]).status_code == 200
    assert cfg()["net0"] == "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,firewall=1,tag=10"


def test_link_down_needs_confirm_and_false_removes_it(api):
    c, cid = api
    r = net(c, cid, "net0", link_down=True)
    assert r.status_code == 400 and "link_down" in r.json()["detail"] and not puts()
    assert net(c, cid, "net0", link_down=True, confirm=True).status_code == 200 and "link_down=1" in cfg()["net0"]
    assert net(c, cid, "net0", link_down=False).status_code == 200 and "link_down" not in cfg()["net0"]
    assert net(c, cid, "net0", link_down=False, clear=["link_down"]).status_code == 422


def test_mtu_and_queues_only_on_virtio_cards(api):
    c, cid = api
    assert net(c, cid, "net1", mtu=1500).status_code == 422 and net(c, cid, "net1", queues=2).status_code == 422 and not puts()
    assert net(c, cid, "net1", rate=3).status_code == 200                                      # le débit marche sur tous les modèles


@pytest.mark.parametrize("body", [
    {"rate": -1}, {"rate": "5"}, {"rate": True}, {"mtu": 0}, {"mtu": 70000}, {"mtu": 1500.5}, {"queues": 65}, {"queues": -1}, {"link_down": "1"},
    {"trunks": ["1_0"]}, {"trunks": [" 10"]}, {"trunks": ["+5"]}, {"trunks": ["١٠"]}, {"trunks": ["0"]}, {"trunks": ["4095"]}, {"trunks": ["30-20"]}, {"trunks": ["a"]}, {"trunks": ["10", "10"]}, {"trunks": ["10;20"]}, {"trunks": ["1-2-3"]},
    {}, {"clear": []}, {"rate": 5, "clear": ["rate"]}, {"clear": ["bridge"]}, {"clear": ["tag"]}, {"mtu": 65530},
])
def test_net_refusals_write_nothing(api, body):
    c, cid = api
    assert net(c, cid, "net0", **body).status_code == 422
    assert not puts()


def test_net_unknown_card_and_machine(api):
    c, cid = api
    assert net(c, cid, "net7", rate=5).status_code == 404
    assert c.patch(f"/api/connections/{cid}/guests/enzo/qemu/999/nets/net0/options", json={"rate": 5}).status_code == 502      # Proxmox : machine inexistante
    assert not puts()


def test_lxc_net_options(api):
    c, cid = api
    assert net(c, cid, "net0", "lxc", 120, rate=5, mtu=1500, trunks=["10"]).status_code == 200
    assert cfg("lxc", 120)["net0"] == "name=eth0,bridge=vmbr0,hwaddr=AA:BB:CC:DD:EE:11,type=veth,ip=dhcp,rate=5,mtu=1500,trunks=10"
    assert net(c, cid, "net0", "lxc", 120, queues=2).status_code == 422                       # queues : VM seulement
    assert net(c, cid, "net0", "lxc", 120, mtu=10).status_code == 422                          # conteneur : 64 à 65535


def test_net_dry_run_and_mac_untouched(api):
    c, cid = api
    r = net(c, cid, "net0", rate=5, dry_run=True)
    assert r.json()["options"]["rate"] == "5" and not puts()
    assert net(c, cid, "net0", rate=5).status_code == 200 and "AA:BB:CC:DD:EE:FF" in cfg()["net0"]


def test_net_silent_non_write_is_reported(api):
    c, cid = api
    ST["noapply"] = True
    assert net(c, cid, "net0", rate=5).status_code == 502


# ------------------------------------------------------------------ CPU
def test_cpu_options_are_written_with_the_digest(api):
    c, cid = api
    r = cpu(c, cid, cpuunits=2000, cpulimit=2.5, affinity="0,5,8-11", confirm=True)
    assert r.status_code == 200, r.text
    assert puts()[0]["form"] == {"cpuunits": "2000", "cpulimit": "2.5", "affinity": "0,5,8-11", "digest": DIGEST}
    assert cfg()["cpuunits"] == "2000"


def test_numbers_read_back_as_floats_are_compared_as_numbers(api):
    c, cid = api
    ST["float_echo"] = True                                                                    # Proxmox renvoie « 4.0 » pour 4
    assert cpu(c, cid, cpulimit=4).status_code == 200 and cfg()["cpulimit"] == "4.0"


def test_cpulimit_whole_number_and_zero(api):
    c, cid = api
    assert cpu(c, cid, cpulimit=4.0).status_code == 200 and puts()[0]["form"]["cpulimit"] == "4"
    assert cpu(c, cid, cpulimit=0).status_code == 200


def test_cpu_option_removed_with_delete(api):
    c, cid = api
    cpu(c, cid, cpuunits=100)
    assert cpu(c, cid, clear=["cpuunits"]).status_code == 200 and "cpuunits" not in cfg() and puts()[-1]["form"]["delete"] == "cpuunits"


def test_affinity_beyond_node_cores_is_refused_before_any_write(api):
    c, cid = api
    r = cpu(c, cid, affinity="0-12", confirm=True)
    assert r.status_code == 422 and "12 cœurs" in r.json()["detail"] and not puts()
    assert cpu(c, cid, affinity="0-11", confirm=True).status_code == 200


def test_affinity_unreadable_node_status_leaves_the_decision_to_proxmox(api):
    c, cid = api
    ST["status_down"] = True
    assert cpu(c, cid, affinity="0-99", confirm=True).status_code == 200


@pytest.mark.parametrize("body", [
    {"cpuunits": 0}, {"cpuunits": 262145}, {"cpuunits": 1.5}, {"cpuunits": "100"}, {"cpuunits": True}, {"cpulimit": -1}, {"cpulimit": 129}, {"cpulimit": "2"},
    {"affinity": "1_0"}, {"affinity": " 1"}, {"affinity": "+1"}, {"affinity": "١"}, {"affinity": "5-3"}, {"affinity": "a"}, {"affinity": "0,,1"}, {"affinity": "0-1-2"}, {"affinity": "0;1"}, {"affinity": ""}, {"hugepages": "4"}, {"hugepages": 2},
    {}, {"clear": []}, {"cpuunits": 100, "clear": ["cpuunits"]}, {"clear": ["cores"]}, {"clear": ["cpu"]},
])
def test_cpu_refusals_write_nothing(api, body):
    c, cid = api
    assert cpu(c, cid, **body).status_code == 422
    assert not puts()


@pytest.mark.parametrize("body,why", [({"hugepages": "any"}, "hugepages"), ({"hugepages": "1024"}, "hugepages"), ({"affinity": "0-3"}, "affinity")])
def test_cpu_risky_options_need_confirm(api, body, why):
    c, cid = api
    r = cpu(c, cid, **body)
    assert r.status_code == 400 and why in r.json()["detail"] and not puts()
    assert cpu(c, cid, confirm=True, **body).status_code == 200


def test_cpu_dry_run_and_silent_non_write(api):
    c, cid = api
    r = cpu(c, cid, cpuunits=100, dry_run=True)
    assert r.json() == {"dry_run": True, "params": {"cpuunits": "100"}, "remove": [], "risks": [], "protected": False} and not puts()
    ST["noapply"] = True
    assert cpu(c, cid, cpuunits=100).status_code == 502


# ------------------------------------------------------------------ transverse
def test_audit_records_the_change_without_volume_names_or_secrets(api):
    c, cid = api
    disk(c, cid, "scsi0", cache="none")
    disk(c, cid, "ide2", cache="none")                                                         # refusé : aussi audité
    net(c, cid, "net0", rate=5)
    cpu(c, cid, cpuunits=100)
    log = c.get("/api/audit").json()
    mine = [e for e in log if e["action"] == "hw-options"]
    assert {(e["status"]) for e in mine} == {"started", "error"} and len(mine) == 4
    text = c.get("/api/audit").text
    assert SECRET not in text and "vm-115-disk-0" not in text and "AA:BB:CC:DD:EE:FF" not in text
    assert any("cache=none" in (e.get("detail") or "") for e in mine)


def test_requires_login_and_validates_path(api):
    c, cid = api
    assert disk(c, cid, "scsi99x", cache="none").status_code == 422
    assert c.patch(f"/api/connections/{cid}/guests/a;b/qemu/115/cpu-options", json={"cpuunits": 1}).status_code == 422
    assert c.patch(f"/api/connections/{cid}/guests/enzo/qemu/99/cpu-options", json={"cpuunits": 1}).status_code == 422
    c.post("/api/auth/logout")
    assert disk(c, cid, "scsi0", cache="none").status_code == 401 and net(c, cid, "net0", rate=5).status_code == 401 and cpu(c, cid, cpuunits=1).status_code == 401
    assert not puts()


def test_config_read_exposes_the_new_options(api):
    c, cid = api
    net(c, cid, "net0", rate=5, mtu=1500, trunks=["10", "20-30"])
    cpu(c, cid, cpuunits=100, affinity="0-3", confirm=True)
    ST["cfgs"][("qemu", 115)]["net0"] += ",link_down=1"
    j = c.get(f"/api/connections/{cid}/guests/enzo/qemu/115/config").json()
    n0 = next(n for n in j["nets"] if n["key"] == "net0")
    assert n0["rate"] == "5" and n0["mtu"] == 1500 and n0["queues"] is None and n0["link_down"] is True and n0["trunks"] == ["10", "20-30"]
    assert j["settings"]["cpuunits"] == "100" and j["settings"]["affinity"] == "0-3"
