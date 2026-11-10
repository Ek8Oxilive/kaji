"""Passthrough PCI, USB et répertoires d'une VM PAR CORRESPONDANCE (`hostpciN`, `usbN`, `virtiofsN`) : validation, construction et lecture sûre.

Un jeton non-root ne peut utiliser que des **correspondances** du datacenter (`mapping=ID`, voir `mappingspec.py`) : les périphériques « bruts » (`host=…`) sont réservés à `root@pam`.
Kaji les affiche (lecture seule) mais ne les crée, ne les modifie et ne les retire jamais. Rien n'est transmis tel quel : les options sont des booléens, des listes blanches ou des
identifiants validés.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .mappingspec import ID as MAPPING_ID

PType = Literal["pci", "usb", "dir"]
KEY = {"pci": re.compile(r"^hostpci([0-9]|1[0-5])$"), "usb": re.compile(r"^usb([0-9]|1[0-3])$"), "dir": re.compile(r"^virtiofs[0-9]$")}
PREFIX = {"pci": "hostpci", "usb": "usb", "dir": "virtiofs"}
SLOTS = {"pci": 16, "usb": 14, "dir": 10}
MDEV = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")
CACHE = ("always", "auto", "metadata", "never")
OPTIONS = {"pci": ("pcie", "rombar", "x-vga", "mdev"), "usb": ("usb3",), "dir": ("cache", "direct-io", "expose-acl", "expose-xattr")}
BOOLS = {"pcie", "rombar", "x-vga", "usb3", "direct-io", "expose-acl", "expose-xattr"}
MAPKEY = {"pci": "mapping", "usb": "mapping", "dir": "dirid"}                          # nom de la propriété qui désigne la correspondance


class Device(BaseModel):
    """Un périphérique à écrire. Les options d'un autre type sont refusées à la construction (`build`)."""
    mapping: str = Field(pattern=MAPPING_ID.pattern)
    pcie: bool | None = None
    rombar: bool | None = None
    x_vga: bool | None = None
    mdev: str | None = Field(default=None, max_length=64)
    usb3: bool | None = None
    cache: Literal["always", "auto", "metadata", "never"] | None = None
    direct_io: bool | None = None
    expose_acl: bool | None = None
    expose_xattr: bool | None = None
    dry_run: bool = False

    @field_validator("mdev")
    @classmethod
    def _mdev(cls, v):
        if v is not None and not MDEV.fullmatch(v):
            raise ValueError("Type de périphérique médié invalide")
        return v


def build(ptype: str, d: Device) -> str:
    """Valeur de `hostpciN` / `usbN` / `virtiofsN` : la correspondance d'abord, puis les options données, dans l'ordre canonique."""
    given = {"pcie": d.pcie, "rombar": d.rombar, "x-vga": d.x_vga, "mdev": d.mdev, "usb3": d.usb3, "cache": d.cache, "direct-io": d.direct_io,
             "expose-acl": d.expose_acl, "expose-xattr": d.expose_xattr}
    extra = [k for k, v in given.items() if v is not None and k not in OPTIONS[ptype]]
    if extra:
        raise ValueError(f"Option(s) inutilisable(s) pour ce type de périphérique : {', '.join(extra)}")
    parts = [f"{MAPKEY[ptype]}={d.mapping}"]
    for k in OPTIONS[ptype]:
        v = given[k]
        if v is not None:
            parts.append(f"{k}={int(v) if k in BOOLS else v}")
    return ",".join(parts)


def parse(ptype: str, key: str, raw) -> dict | None:
    """Valeur de configuration -> dict sûr. `raw: true` si le périphérique n'est pas une correspondance (hôte brut) : affiché, jamais modifiable."""
    if not isinstance(raw, str) or len(raw) > 1000 or not KEY[ptype].fullmatch(key):
        return None
    kv: dict[str, str] = {}
    bare = None
    for i, part in enumerate(raw.split(",")):
        k, eq, v = part.partition("=")
        if eq and k not in kv:
            kv[k] = v
        elif not eq and i == 0:
            bare = part                                                               # `0000:01:00.0` ou `1-13` sans `host=`
    mapping = kv.get(MAPKEY[ptype])
    if mapping is not None and not MAPPING_ID.fullmatch(mapping):
        mapping = None
    host = kv.get("host") or bare
    out = {"key": key, "type": ptype, "mapping": mapping, "raw": mapping is None,
           "host": (host[:120] if host and re.fullmatch(r"[0-9A-Za-z:.;\-_/]+", host) else None) if mapping is None else None}
    for opt in OPTIONS[ptype]:
        v = kv.get(opt)
        if opt in BOOLS:
            out[opt.replace("-", "_")] = None if v is None else v == "1"
        elif opt == "cache":
            out["cache"] = v if v in CACHE else None
        else:
            out["mdev"] = v if v and MDEV.fullmatch(v) else None
    known = set(OPTIONS[ptype]) | {MAPKEY[ptype], "host"}
    out["other"] = sorted(k for k in kv if k not in known and re.fullmatch(r"[a-z0-9\-]{1,32}", k))[:10]      # options inconnues : signalées, jamais réécrites par Kaji
    return out


def shape_devices(cfg, ptype: str) -> list[dict]:
    rows = [parse(ptype, k, v) for k, v in (cfg.items() if isinstance(cfg, dict) else []) if isinstance(k, str) and KEY[ptype].fullmatch(k)]
    return sorted((r for r in rows if r), key=lambda r: int(r["key"].removeprefix(PREFIX[ptype])))


def free_key(cfg: dict, ptype: str) -> str | None:
    return next((f"{PREFIX[ptype]}{i}" for i in range(SLOTS[ptype]) if f"{PREFIX[ptype]}{i}" not in cfg), None)
