"""Lecture / écriture sûre de la configuration matérielle d'une VM ou d'un LXC.

Proxmox stocke chaque périphérique dans une chaîne (« virtio=AA:BB:..,bridge=vmbr0,tag=10 »).
On la décompose en champs structurés, et on ne réécrit que des champs validés : jamais de clé libre.
"""
import ipaddress
import re

NET_MODELS = {"virtio", "e1000", "e1000e", "rtl8139", "vmxnet3"}
DISK_KEY = re.compile(r"^(scsi|virtio|sata|ide)\d+$")
NET_KEY = re.compile(r"^net\d+$")
MP_KEY = re.compile(r"^mp\d+$")
BRIDGE = re.compile(r"^[A-Za-z0-9_.\-]{1,15}$")
ISO = re.compile(r"^[A-Za-z0-9_.\-]+:iso/[A-Za-z0-9_.+\- ]+\.iso$")
SIZE = re.compile(r"^(\d+(?:\.\d+)?)([KMGT]?)$")

QEMU_SETTINGS = ("name", "memory", "balloon", "cores", "sockets", "vcpus", "cpu", "numa", "bios", "machine",
                 "ostype", "boot", "agent", "onboot", "scsihw")
LXC_SETTINGS = ("hostname", "memory", "swap", "cores", "cpulimit", "cpuunits", "ostype", "onboot", "unprivileged")


def parse_size(s: str | None) -> int | None:
    m = SIZE.match(s or "")
    if not m:
        return None
    return int(float(m.group(1)) * {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}[m.group(2)])


def _split(value: str) -> list[str]:
    return [p for p in str(value).split(",") if p]


def parse_net(key: str, value: str, lxc: bool) -> dict:
    model = mac = None
    opts: dict[str, str] = {}
    for part in _split(value):
        k, _, v = part.partition("=")
        if not lxc and k in NET_MODELS and model is None:
            model, mac = k, v
        else:
            opts[k] = v
    if lxc:
        mac = opts.get("hwaddr")
    return {"key": key, "model": model, "mac": mac, "bridge": opts.get("bridge"),
            "tag": int(opts["tag"]) if opts.get("tag", "").isdigit() else None,
            "firewall": opts.get("firewall") == "1", "name": opts.get("name"), "ip": opts.get("ip"), "_raw": value}


def rebuild_net(raw: str, lxc: bool, *, bridge: str | None = None, tag: int | None | bool = False,
                firewall: bool | None = None) -> str:
    """Réécrit la chaîne d'une carte réseau en ne touchant qu'aux champs demandés (la MAC est conservée).

    tag : False = inchangé, None = retirer le VLAN, int = nouveau VLAN.
    """
    parts: list[tuple[str, str]] = []
    for part in _split(raw):
        k, _, v = part.partition("=")
        parts.append((k, v))
    d = dict(parts)
    if bridge is not None:
        d["bridge"] = bridge
    if tag is not False:
        if tag is None:
            d.pop("tag", None)
        else:
            d["tag"] = str(tag)
    if firewall is not None:
        d["firewall"] = "1" if firewall else "0"
    order = [k for k, _ in parts] + [k for k in d if k not in dict(parts)]
    return ",".join(f"{k}={d[k]}" for k in order if k in d)


def parse_disk(key: str, value: str) -> dict:
    parts = _split(value)
    spec = parts[0] if parts and "=" not in parts[0] else ""
    opts = dict(p.partition("=")[::2] for p in parts[1:] if "=" in p)
    cdrom = opts.get("media") == "cdrom"
    storage, _, volume = spec.partition(":")
    return {"key": key, "kind": "cdrom" if cdrom else "disk", "storage": storage or None,
            "volume": volume or None, "empty": spec in ("", "none"), "size": opts.get("size"),
            "size_bytes": parse_size(opts.get("size")), "options": {k: v for k, v in opts.items() if k not in ("size", "media")}}


def normalize(gtype: str, cfg: dict, pending: list[dict]) -> dict:
    lxc = gtype == "lxc"
    settings = {k: cfg[k] for k in (LXC_SETTINGS if lxc else QEMU_SETTINGS) if k in cfg}
    disks = []
    for k, v in cfg.items():
        if lxc and (k == "rootfs" or MP_KEY.match(k)):
            d = parse_disk(k, v)
            d["kind"] = "disk"
            disks.append(d)
        elif not lxc and DISK_KEY.match(k):
            disks.append(parse_disk(k, v))
    nets = [{k2: v2 for k2, v2 in parse_net(k, v, lxc).items() if k2 != "_raw"} for k, v in cfg.items() if NET_KEY.match(k)]
    disks.sort(key=lambda d: d["key"]); nets.sort(key=lambda n: n["key"])
    unused = sorted(({"key": k, "volume": v, "storage": str(v).partition(":")[0] or None} for k, v in cfg.items() if UNUSED_KEY.match(k)),
                    key=lambda u: u["key"])
    pend = [{"key": p["key"], "value": p.get("value"), "pending": p.get("pending"), "delete": bool(p.get("delete"))}
            for p in pending if "pending" in p or p.get("delete")]
    return {"type": gtype, "settings": settings, "disks": disks, "nets": nets, "pending": pend,
            "reboot_required": bool(pend), "unused": unused, "boot_order": [] if lxc else parse_boot_order(cfg.get("boot"))}


BOOT_KEY = re.compile(r"^((scsi|virtio|sata|ide)\d+|net\d+)$")


def parse_boot_order(value: str | None) -> list[str]:
    """« order=scsi0;ide2;net0 » -> ['scsi0', 'ide2', 'net0']. Les formats anciens (c, dn…) ne sont pas interprétés."""
    for part in str(value or "").split(","):
        k, _, v = part.partition("=")
        if k == "order":
            return [x for x in v.split(";") if BOOT_KEY.match(x)]
    return []


def next_net_index(cfg: dict) -> int:
    used = {int(k[3:]) for k in cfg if NET_KEY.match(k)}
    for n in range(32):
        if n not in used:
            return n
    raise ValueError("Nombre maximal de cartes réseau atteint (32)")


def validate_ip(ip: str | None, gateway: str | None) -> None:
    if ip in (None, "", "dhcp", "manual"):
        if gateway:
            raise ValueError("Une passerelle n'a de sens qu'avec une adresse IP statique")
        return
    try:
        if "/" not in ip:
            raise ValueError("masque manquant")      # Proxmox exige la notation CIDR (192.168.1.50/24)
        ipaddress.ip_interface(ip)
        if gateway:
            ipaddress.ip_address(gateway)
    except ValueError:
        raise ValueError("Adresse IP (CIDR, ex. 192.168.1.50/24) ou passerelle invalide") from None


def build_new_net(lxc: bool, index: int, *, bridge: str, model: str = "virtio", tag: int | None = None,
                  firewall: bool = False, ip: str | None = None, gateway: str | None = None) -> str:
    """Chaîne d'une nouvelle carte réseau. La MAC est attribuée par Proxmox."""
    validate_ip(ip, gateway)
    parts = [f"name=eth{index}", f"bridge={bridge}", "type=veth"] if lxc else [model, f"bridge={bridge}"]
    if lxc and ip:
        parts.append(f"ip={ip}")
        if gateway:
            parts.append(f"gw={gateway}")
    if tag:
        parts.append(f"tag={tag}")
    if firewall:
        parts.append("firewall=1")
    return ",".join(parts)


UNUSED_KEY = re.compile(r"^unused\d+$")
BUS_LIMITS = {"scsi": 31, "virtio": 16, "sata": 6, "ide": 4}
MP_PATH = re.compile(r"^/[A-Za-z0-9_.\-/]{1,200}$")


def next_disk_key(cfg: dict, bus: str) -> str:
    used = {int(k[len(bus):]) for k in cfg if re.fullmatch(rf"{bus}\d+", k)}
    for n in range(BUS_LIMITS[bus]):
        if n not in used:
            return f"{bus}{n}"
    raise ValueError(f"Plus d'emplacement libre sur le bus {bus}")


def next_mp_key(cfg: dict) -> str:
    used = {int(k[2:]) for k in cfg if MP_KEY.match(k)}
    for n in range(256):
        if n not in used:
            return f"mp{n}"
    raise ValueError("Nombre maximal de points de montage atteint")


def check_mp_path(path: str) -> str:
    if not MP_PATH.match(path) or ".." in path or "//" in path or path == "/" or path.endswith(","):
        raise ValueError("Chemin de montage invalide (ex. /srv/data)")
    return path


def build_new_disk(storage: str, size_gb: int, mp: str | None = None) -> str:
    return f"{storage}:{size_gb}" + (f",mp={check_mp_path(mp)}" if mp else "")
