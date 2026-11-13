"""Options fines d'un disque, d'une carte réseau et du CPU d'une VM (lot #377).

Noms, énumérations et bornes lus dans le schéma officiel de Proxmox 9 (`apidoc.js`, `scsi[n]`, `net[n]`, `cpuunits`, `cpulimit`, `affinity`,
`hugepages`). Liste blanche : une option inconnue est ignorée, jamais transmise ; une valeur hors liste est refusée. On ne réécrit que les
options demandées dans la chaîne du périphérique : le volume, la taille, la MAC et les options que Kaji ne gère pas sont conservés tels quels.
Les réglages qui peuvent faire perdre des données ou couper la machine exigent `confirm`, décidé par le SERVEUR.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field, StrictBool, StrictInt, field_validator

DISK_KEY = re.compile(r"^(scsi|virtio|sata|ide)(\d+)$")
NET_KEY = re.compile(r"^net\d+$")
CPUSET = re.compile(r"^[0-9]{1,4}(-[0-9]{1,4})?(,[0-9]{1,4}(-[0-9]{1,4})?)*$")          # chiffres ASCII seulement (\d accepterait l'Unicode)
TRUNK = re.compile(r"^[0-9]{1,4}(-[0-9]{1,4})?$")

DISK_BOOLS = ("iothread", "ssd", "backup", "ro", "replicate", "detect_zeroes")
DISK_NUMS = ("mbps", "mbps_rd", "mbps_wr")                       # Mo/s, nombre décimal
DISK_INTS = ("iops", "iops_rd", "iops_wr")                       # opérations par seconde
DISK_ENUMS = {"cache": ("none", "writethrough", "writeback", "unsafe", "directsync"), "discard": ("ignore", "on"), "aio": ("native", "threads", "io_uring")}
DISK_FIELDS = tuple(DISK_ENUMS) + DISK_BOOLS + DISK_NUMS + DISK_INTS
RISKY_CACHE = {"unsafe": "cache=unsafe : des données écrites peuvent être perdues en cas de coupure",
               "writeback": "cache=writeback : des données écrites peuvent être perdues en cas de coupure"}


def _no_bool_or_text(v):
    """Un nombre est un nombre : ni booléen, ni texte (pydantic accepterait « 5 » ou True)."""
    if isinstance(v, (bool, str)):
        raise ValueError("nombre attendu")
    return v


class _Num(BaseModel):
    @field_validator("*", mode="before")
    @classmethod
    def _strict_numbers(cls, v, info):
        if info.field_name in DISK_NUMS + DISK_INTS + ("rate", "cpulimit", "cpuunits", "mtu", "queues"):
            return _no_bool_or_text(v) if v is not None else v
        return v


class DiskOptions(_Num):
    cache: Literal["none", "writethrough", "writeback", "unsafe", "directsync"] | None = None
    discard: Literal["ignore", "on"] | None = None
    aio: Literal["native", "threads", "io_uring"] | None = None
    iothread: StrictBool | None = None
    ssd: StrictBool | None = None
    backup: StrictBool | None = None
    ro: StrictBool | None = None
    replicate: StrictBool | None = None
    detect_zeroes: StrictBool | None = None
    mbps: float | None = Field(default=None, ge=0, le=100000)
    mbps_rd: float | None = Field(default=None, ge=0, le=100000)
    mbps_wr: float | None = Field(default=None, ge=0, le=100000)
    iops: int | None = Field(default=None, ge=0, le=10_000_000)
    iops_rd: int | None = Field(default=None, ge=0, le=10_000_000)
    iops_wr: int | None = Field(default=None, ge=0, le=10_000_000)
    clear: list[Literal["cache", "discard", "aio", "iothread", "ssd", "backup", "ro", "replicate", "detect_zeroes", "mbps", "mbps_rd", "mbps_wr",
                        "iops", "iops_rd", "iops_wr"]] = Field(default=[], max_length=15)
    confirm: bool = False
    dry_run: bool = False


class NetOptions(_Num):
    rate: float | None = Field(default=None, ge=0, le=1_000_000)             # Mo/s, 0 = illimité
    mtu: int | None = Field(default=None, ge=1, le=65535)
    queues: int | None = Field(default=None, ge=0, le=64)
    link_down: StrictBool | None = None
    trunks: list[str] | None = Field(default=None, max_length=32)
    clear: list[Literal["rate", "mtu", "queues", "link_down", "trunks"]] = Field(default=[], max_length=5)
    confirm: bool = False
    dry_run: bool = False

    @field_validator("trunks")
    @classmethod
    def _trunks(cls, v):
        if v is None:
            return v
        for t in v:
            if not TRUNK.fullmatch(t):
                raise ValueError("VLAN invalide (nombre ou plage, ex. 10 ou 20-30)")
            lo, _, hi = t.partition("-")
            if not 1 <= int(lo) <= 4094 or (hi and not int(lo) <= int(hi) <= 4094):
                raise ValueError("VLAN hors de 1 à 4094, ou plage à l'envers")
        if len(set(v)) != len(v):
            raise ValueError("VLAN en double")
        return v


class CpuOptions(_Num):
    cpuunits: int | None = Field(default=None, ge=1, le=262144)
    cpulimit: float | None = Field(default=None, ge=0, le=128)
    affinity: str | None = Field(default=None, max_length=100)
    hugepages: Literal["any", "2", "1024"] | None = None
    clear: list[Literal["cpuunits", "cpulimit", "affinity", "hugepages"]] = Field(default=[], max_length=4)
    confirm: bool = False
    dry_run: bool = False

    @field_validator("affinity")
    @classmethod
    def _affinity(cls, v):
        if v is None:
            return v
        if not CPUSET.fullmatch(v):
            raise ValueError("Cœurs invalides (ex. 0,5,8-11)")
        for part in v.split(","):
            lo, _, hi = part.partition("-")
            if hi and int(lo) > int(hi):
                raise ValueError("Plage de cœurs à l'envers")
        return v


def fmt_num(n: float | int) -> str:
    return str(int(n)) if float(n).is_integer() else str(round(float(n), 3))


def split_opts(raw: str) -> tuple[str | None, list[tuple[str, str]]]:
    """« local-lvm:vm-1-disk-0,size=32G,cache=none » -> (« local-lvm:vm-1-disk-0 », [(size, 32G), (cache, none)]). Tête absente : (None, …)."""
    parts = [p for p in str(raw).split(",") if p]
    head = parts[0] if parts and "=" not in parts[0] else None
    rest = parts[1:] if head is not None else parts
    return head, [(k, v) for k, _, v in (p.partition("=") for p in rest)]


def join_opts(head: str | None, opts: list[tuple[str, str]]) -> str:
    return ",".join(([head] if head else []) + [f"{k}={v}" for k, v in opts])


def _apply(opts: list[tuple[str, str]], sets: dict[str, str], clear: list[str]) -> list[tuple[str, str]]:
    """Garde l'ordre existant, remplace en place, ajoute à la fin, retire ce qui est demandé."""
    out = [(k, sets.pop(k, v)) for k, v in opts if k not in clear]
    out += list(sets.items())
    return out


def disk_changes(body: DiskOptions) -> dict[str, str]:
    d: dict[str, str] = {}
    for k in DISK_ENUMS:
        if getattr(body, k) is not None:
            d[k] = getattr(body, k)
    for k in DISK_BOOLS:
        if getattr(body, k) is not None:
            d[k] = "1" if getattr(body, k) else "0"
    for k in DISK_NUMS + DISK_INTS:
        if getattr(body, k) is not None:
            d[k] = fmt_num(getattr(body, k))
    return d


def build_disk(raw: str, key: str, body: DiskOptions, scsihw: str | None) -> tuple[str, list[str]]:
    """Chaîne du disque réécrite + risques (qui exigent `confirm`). `ValueError` = refus 422."""
    m = DISK_KEY.fullmatch(key)
    head, opts = split_opts(raw)
    if not m or head is None:
        raise ValueError("Disque inconnu ou format de configuration non géré")
    if dict(opts).get("media") == "cdrom" or "cloudinit" in head:
        raise ValueError("Un lecteur CD/DVD ou cloud-init n'a pas ces options")
    sets, clear = disk_changes(body), list(body.clear)
    if set(sets) & set(clear):
        raise ValueError("Option à la fois modifiée et retirée")
    if not sets and not clear:
        raise ValueError("Aucune modification demandée")
    new = _apply(opts, dict(sets), clear)
    final = dict(new)
    bus = m.group(1)
    if final.get("iothread") == "1" and not (bus == "virtio" or (bus == "scsi" and scsihw == "virtio-scsi-single")):
        raise ValueError("iothread : seulement sur un disque virtio, ou scsi avec le contrôleur virtio-scsi-single")
    if final.get("ssd") == "1" and bus == "virtio":
        raise ValueError("ssd : pas disponible sur un disque virtio")
    if "mbps" in final and ("mbps_rd" in final or "mbps_wr" in final):
        raise ValueError("mbps ne se combine pas avec mbps_rd / mbps_wr")
    if "iops" in final and ("iops_rd" in final or "iops_wr" in final):
        raise ValueError("iops ne se combine pas avec iops_rd / iops_wr")
    risks = []
    if sets.get("cache") in RISKY_CACHE:
        risks.append(RISKY_CACHE[sets["cache"]])
    if sets.get("backup") == "0":
        risks.append("backup=0 : ce disque ne sera plus inclus dans les sauvegardes")
    return join_opts(head, new), risks


def build_net(raw: str, key: str, lxc: bool, body: NetOptions) -> tuple[str, list[str]]:
    head, opts = split_opts(raw)                                   # pour une carte, la 1re entrée est « modèle=MAC » (VM) : elle reste avec les options
    if not NET_KEY.fullmatch(key):
        raise ValueError("Carte réseau inconnue")
    sets: dict[str, str] = {}
    if body.rate is not None:
        sets["rate"] = fmt_num(body.rate)
    if body.mtu is not None:
        sets["mtu"] = str(body.mtu)
    if body.queues is not None:
        sets["queues"] = str(body.queues)
    if body.link_down is True:
        sets["link_down"] = "1"
    if body.trunks is not None:
        sets["trunks"] = ";".join(body.trunks)
    clear = list(body.clear) + (["link_down"] if body.link_down is False else [])
    if body.link_down is False and "link_down" in body.clear:
        raise ValueError("Option à la fois modifiée et retirée")
    if set(sets) & set(clear):
        raise ValueError("Option à la fois modifiée et retirée")
    if not sets and not clear:
        raise ValueError("Aucune modification demandée")
    model = next((k for k, _ in opts if k in ("virtio", "e1000", "e1000e", "rtl8139", "vmxnet3", "e1000-82540em", "e1000-82544gc", "e1000-82545em", "i82551",
                                               "i82557b", "i82559er", "ne2k_isa", "ne2k_pci", "pcnet")), None)
    if not lxc and ("mtu" in sets or "queues" in sets) and model != "virtio":
        raise ValueError("mtu et queues : seulement sur une carte de modèle virtio")
    if lxc and "queues" in sets:
        raise ValueError("queues : seulement sur une carte de VM")
    if lxc and "mtu" in sets and not 64 <= body.mtu <= 65535:
        raise ValueError("mtu d'un conteneur : de 64 à 65535")
    if not lxc and "mtu" in sets and body.mtu > 65520:
        raise ValueError("mtu d'une VM : de 1 à 65520")
    new = _apply(opts, dict(sets), clear)
    risks = []
    if sets.get("link_down") == "1":
        risks.append("link_down : la machine perd son réseau tant que le câble est débranché")
    return join_opts(head, new), risks


def build_cpu(body: CpuOptions, node_cpus: int | None) -> tuple[dict[str, str | int | float], list[str], list[str]]:
    """(paramètres à écrire, options à retirer, risques)."""
    sets: dict[str, str | int | float] = {}
    if body.cpuunits is not None:
        sets["cpuunits"] = body.cpuunits
    if body.cpulimit is not None:
        sets["cpulimit"] = fmt_num(body.cpulimit)
    if body.affinity is not None:
        sets["affinity"] = body.affinity
    if body.hugepages is not None:
        sets["hugepages"] = body.hugepages
    clear = list(body.clear)
    if set(sets) & set(clear):
        raise ValueError("Option à la fois modifiée et retirée")
    if not sets and not clear:
        raise ValueError("Aucune modification demandée")
    if body.affinity is not None and node_cpus:
        top = max(int(n) for part in body.affinity.split(",") for n in part.split("-"))
        if top >= node_cpus:
            raise ValueError(f"Le nœud n'a que {node_cpus} cœurs (numérotés de 0 à {node_cpus - 1})")
    risks = []
    if body.hugepages is not None:
        risks.append("hugepages : la machine ne démarrera pas si le nœud n'a pas assez de pages réservées")
    if body.affinity is not None:
        risks.append("affinity : la machine n'utilisera que ces cœurs du nœud (elle sera aussi limitée après une migration)")
    return sets, clear, risks
