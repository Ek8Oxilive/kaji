"""Correspondances de ressources du datacenter (PCI, USB, répertoires) : validation, construction des entrées et lecture sûre.

Formats LUS sur le vrai Proxmox 9 (`/usr/share/pve-docs/api-viewer/apidoc.js`, 2026-11-10) : une correspondance = `id`, `description`, une liste `map` de chaînes
« propriété=valeur,… » (une par entrée, `node` obligatoire) ; pci : `path` (adresses PCI séparées par `;`), `id` (vendeur:périphérique, 4+4 hexadécimaux), `iommugroup`,
`subsystem-id`, plus `mdev` et `live-migration-capable` sur la correspondance ; usb : `id` (obligatoire), `path` (bus-port) ; dir : `path` (absolu). Rien n'est transmis tel quel.
"""
import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

MType = Literal["pci", "usb", "dir"]
HType = Literal["pci", "usb"]
ID = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,63}$")
NODE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9\-]{0,62})$")
HEX_ID = re.compile(r"^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}$")
PCI_ADDR = r"[0-9a-f]{4,}:[0-9a-f]{2}:[0-9a-f]{2}(?:\.[0-9a-f])?"
PCI_PATH = re.compile(rf"^{PCI_ADDR}(?:;{PCI_ADDR})*$")
PCI_FULL_ADDR = re.compile(r"^[0-9a-f]{4,}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]$")
USB_PATH = re.compile(r"^\d{1,4}-\d{1,4}(?:\.\d{1,4})*$")
DIR_PATH = re.compile(r"^/(?:[A-Za-z0-9_.+\-]+(?:/[A-Za-z0-9_.+\-]+)*)?/?$")
ENTRY_DESC = re.compile(r"^[^\x00-\x1f\x7f,=\"'\\]{1,200}$")                        # dans une chaîne « k=v,k=v » : ni virgule, ni égal, ni guillemet
TOP_DESC = re.compile(r"^[^\x00-\x1f\x7f]{1,500}$")
CLEARABLE = Literal["description", "mdev", "live-migration-capable"]
MAX_ENTRIES, MAX_ROWS = 32, 500
ENTRY_KEYS = {"pci": ("node", "path", "id", "iommugroup", "subsystem-id", "description"), "usb": ("node", "id", "path", "description"), "dir": ("node", "path")}


class MapEntry(BaseModel):
    node: str = Field(pattern=NODE.pattern)
    path: str | None = Field(default=None, max_length=300)
    id: str | None = Field(default=None, max_length=9)
    iommugroup: int | None = Field(default=None, ge=0, le=65535)
    subsystem_id: str | None = Field(default=None, max_length=9)
    description: str | None = Field(default=None, max_length=200)

    @field_validator("id", "subsystem_id")
    @classmethod
    def _hex(cls, v):
        if v is not None and not HEX_ID.fullmatch(v):
            raise ValueError("Identifiant attendu : vendeur:périphérique, 4 + 4 chiffres hexadécimaux (ex. 8086:1903)")
        return v.lower() if v else v

    @field_validator("description")
    @classmethod
    def _desc(cls, v):
        if v is not None and not ENTRY_DESC.fullmatch(v):
            raise ValueError("Description invalide (sans virgule, égal, guillemet ni retour à la ligne)")
        return v


def _check_desc(v: str | None) -> str | None:
    if v is not None and not TOP_DESC.fullmatch(v):
        raise ValueError("Description invalide (500 caractères au plus, sur une seule ligne)")
    return v


class MappingCreate(BaseModel):
    id: str = Field(pattern=ID.pattern)
    description: str | None = Field(default=None, max_length=500)
    map: list[MapEntry] = Field(min_length=1, max_length=MAX_ENTRIES)
    mdev: bool | None = None
    live_migration_capable: bool | None = None
    dry_run: bool = False

    @field_validator("description")
    @classmethod
    def _d(cls, v):
        return _check_desc(v)


class MappingUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    map: list[MapEntry] | None = Field(default=None, min_length=1, max_length=MAX_ENTRIES)
    mdev: bool | None = None
    live_migration_capable: bool | None = None
    clear: list[CLEARABLE] = Field(default=[], max_length=3)
    digest: str | None = Field(default=None, max_length=64)
    dry_run: bool = False

    @field_validator("description")
    @classmethod
    def _d(cls, v):
        return _check_desc(v)


def entry_string(mtype: str, e: MapEntry) -> str:
    """Chaîne d'une entrée pour Proxmox, validée selon le type (les propriétés d'un autre type sont refusées)."""
    given = {"node": e.node, "path": e.path, "id": e.id, "iommugroup": e.iommugroup, "subsystem-id": e.subsystem_id, "description": e.description}
    extra = [k for k, v in given.items() if v is not None and k not in ENTRY_KEYS[mtype]]
    if extra:
        raise ValueError(f"Propriété(s) inutilisable(s) pour une correspondance {mtype} : {', '.join(extra)}")
    if mtype == "pci":
        if not e.path or not PCI_PATH.fullmatch(e.path):
            raise ValueError("Chemin PCI invalide (adresses du type 0000:00:02.0, séparées par « ; »)")
        if not e.id:
            raise ValueError("L'identifiant vendeur:périphérique est obligatoire pour une entrée PCI")
    elif mtype == "usb":
        if not e.id:
            raise ValueError("L'identifiant vendeur:produit est obligatoire pour une entrée USB")
        if e.path is not None and not USB_PATH.fullmatch(e.path):
            raise ValueError("Chemin USB invalide (bus-port, ex. 1-13)")
    else:
        if not e.path or not DIR_PATH.fullmatch(e.path) or ".." in e.path.split("/"):
            raise ValueError("Chemin de répertoire invalide (absolu, sans « .. »)")
    return ",".join(f"{k}={given[k]}" for k in ENTRY_KEYS[mtype] if given[k] is not None)


def build_map(mtype: str, entries: list[MapEntry]) -> list[str]:
    out = [entry_string(mtype, e) for e in entries]
    if len(set(out)) != len(out):
        raise ValueError("Deux entrées identiques")
    return out


def build_params(mtype: str, body: MappingCreate | MappingUpdate, clear: list[str]) -> tuple[dict, list[str]]:
    """(paramètres à écrire, propriétés à retirer). `map` est une liste (paramètre répété) ; `mdev` et `live-migration-capable` n'existent que pour pci."""
    p: dict = {}
    if body.map is not None:
        p["map"] = build_map(mtype, body.map)
    if body.description is not None:
        p["description"] = body.description
    for k, v in (("mdev", body.mdev), ("live-migration-capable", body.live_migration_capable)):
        if v is not None:
            if mtype != "pci":
                raise ValueError(f"« {k} » n'existe que pour une correspondance PCI")
            p[k] = 1 if v else 0
    delete = list(dict.fromkeys(clear))
    bad = [k for k in delete if k in ("mdev", "live-migration-capable") and mtype != "pci"]
    if bad:
        raise ValueError(f"« {bad[0]} » n'existe que pour une correspondance PCI")
    clash = [k for k in delete if k in p]
    if clash:
        raise ValueError(f"Réglage à la fois modifié et retiré : {', '.join(clash)}")
    return p, delete


# ------------------------------------------------------------------ lecture
def _text(v, n: int) -> str | None:
    return v[:n] if isinstance(v, str) and v and not re.search(r"[\x00-\x1f\x7f]", v) else None


def _b(v) -> bool | None:
    if isinstance(v, bool):
        return v
    if v in (0, 1, "0", "1"):
        return str(v) == "1"
    return None


def parse_entry(mtype: str, raw) -> dict | None:
    """Entrée « k=v,k=v » -> dict aux seules propriétés connues et valides (le reste est écarté)."""
    if not isinstance(raw, str) or len(raw) > 1000:
        return None
    kv = {}
    for part in raw.split(","):
        k, _, v = part.partition("=")
        if k in ENTRY_KEYS[mtype] and k not in kv:
            kv[k] = v
    if not NODE.fullmatch(kv.get("node", "")):
        return None
    path = kv.get("path")
    ok_path = {"pci": PCI_PATH, "usb": USB_PATH}.get(mtype)
    if mtype == "dir":
        path = path if path and DIR_PATH.fullmatch(path) and ".." not in path.split("/") else None
    elif path is not None and not ok_path.fullmatch(path):
        path = None
    group = kv.get("iommugroup")
    return {"node": kv["node"], "path": path, "id": kv["id"].lower() if HEX_ID.fullmatch(kv.get("id", "")) else None,
            "iommugroup": int(group) if group and group.isdigit() and int(group) <= 65535 else None,
            "subsystem_id": kv["subsystem-id"].lower() if HEX_ID.fullmatch(kv.get("subsystem-id", "")) else None,
            "description": kv.get("description") if ENTRY_DESC.fullmatch(kv.get("description", "")) else None}


def shape_mapping(raw, mtype: str) -> dict | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not ID.fullmatch(raw["id"]):
        return None
    entries = [e for e in (parse_entry(mtype, m) for m in (raw.get("map") if isinstance(raw.get("map"), list) else [])[:MAX_ENTRIES]) if e]
    checks = [m for c in (raw.get("checks") if isinstance(raw.get("checks"), list) else [])[:64] if isinstance(c, dict) for m in [_text(c.get("message"), 300)] if m]
    out = {"id": raw["id"], "type": mtype, "description": _text(raw.get("description"), 500), "map": entries, "checks": checks, "error": _text(raw.get("error"), 300),
           "mdev": _b(raw.get("mdev")) if mtype == "pci" else None, "live_migration_capable": _b(raw.get("live-migration-capable")) if mtype == "pci" else None,
           "digest": raw["digest"] if isinstance(raw.get("digest"), str) and re.fullmatch(r"[0-9a-fA-F]{1,64}", raw["digest"]) else None}
    return out


def shape_list(raw, mtype: str) -> list[dict]:
    rows = [r for r in (shape_mapping(x, mtype) for x in (raw if isinstance(raw, list) else [])[:MAX_ROWS]) if r]
    return sorted(rows, key=lambda r: r["id"])


def digest_of(d: dict) -> str:
    """Empreinte de la correspondance telle que Kaji la montre (le `digest` de Proxmox, s'il existe, est gardé à part)."""
    core = {k: v for k, v in d.items() if k not in ("digest", "checks", "error")}
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()[:40]


def _hex4(v) -> str | None:
    s = v.lower().removeprefix("0x") if isinstance(v, str) else None
    return s if s and re.fullmatch(r"[0-9a-f]{4}", s) else None


def _int(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 10**6 else None


def shape_hardware(raw, htype: str) -> list[dict]:
    """Matériel détecté d'un nœud, prêt à servir d'entrée de correspondance (`map_id`, `map_path`)."""
    out = []
    for r in (raw if isinstance(raw, list) else [])[:MAX_ROWS]:
        if not isinstance(r, dict):
            continue
        if htype == "pci":
            addr, ven, dev = r.get("id"), _hex4(r.get("vendor")), _hex4(r.get("device"))
            if not isinstance(addr, str) or not PCI_FULL_ADDR.fullmatch(addr) or not ven or not dev:
                continue
            sv, sd = _hex4(r.get("subsystem_vendor")), _hex4(r.get("subsystem_device"))
            out.append({"id": addr, "iommugroup": _int(r.get("iommugroup")), "map_id": f"{ven}:{dev}", "subsystem_id": f"{sv}:{sd}" if sv and sd else None,
                        "vendor_name": _text(r.get("vendor_name"), 120), "device_name": _text(r.get("device_name"), 120), "mdev": _b(r.get("mdev")),
                        "class": _text(r.get("class"), 12)})
        else:
            ven, prod, bus, port = _hex4(r.get("vendid")), _hex4(r.get("prodid")), _int(r.get("busnum")), _int(r.get("port"))
            if not ven or not prod:
                continue
            out.append({"map_id": f"{ven}:{prod}", "map_path": f"{bus}-{port}" if bus is not None and port else None, "busnum": bus, "port": port,
                        "product": _text(r.get("product"), 120), "manufacturer": _text(r.get("manufacturer"), 120), "class": _int(r.get("class")),
                        "speed": _text(str(r.get("speed")) if r.get("speed") is not None else None, 20)})
    return out
