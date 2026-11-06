"""Mise en forme des stockages et de leur contenu (lecture seule) : tolérante aux données illisibles."""
import re
from datetime import datetime, timezone
from typing import Literal

# Types de contenu connus de Proxmox ; sert aussi de liste blanche pour le paramètre `content`.
ContentType = Literal["images", "rootdir", "iso", "vztmpl", "backup", "snippets"]
CONTENT_TYPES: tuple[str, ...] = ("images", "rootdir", "iso", "vztmpl", "backup", "snippets")


_DIGITS = re.compile(r"-?[0-9]+")


def _int(v) -> int | None:
    """Entier ou None : une valeur absente ou illisible ne doit jamais faire échouer la liste
    (ni `--5`, ni `inf`, ni `NaN`, ni un nombre démesuré)."""
    if isinstance(v, bool):
        return None
    try:
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str) and _DIGITS.fullmatch(v.strip()):
            return int(v)
    except (ValueError, OverflowError):
        pass
    return None


def _str(v) -> str | None:
    """Texte ou None : une valeur d'un autre type ne doit pas faire échouer un tri."""
    return v if isinstance(v, str) else None


def _contents(raw) -> list[str]:
    """`"backup,iso"` -> `["iso", "backup"]` (ordre fixe de `CONTENT_TYPES`) ; les types inconnus sont ignorés."""
    if not isinstance(raw, str):
        return []
    wanted = {c.strip() for c in raw.split(",")}
    return [c for c in CONTENT_TYPES if c in wanted]


def shape_storages(data) -> list[dict]:
    """Une entrée par (stockage, nœud), comme `/cluster/resources`. Les anciens champs sont conservés tels quels
    (l'interface s'en sert) ; `contents`, `used`, `total`, `free`, `active` et `nodes` s'y ajoutent."""
    rows = [r for r in (data if isinstance(data, list) else [])
            if isinstance(r, dict) and isinstance(r.get("storage"), str) and r["storage"]]
    carried: dict[str, set[str]] = {}
    for r in rows:
        if isinstance(r.get("node"), str):
            carried.setdefault(r["storage"], set()).add(r["node"])
    out = []
    for r in rows:
        used, total = _int(r.get("disk")), _int(r.get("maxdisk"))
        out.append({
            "storage": r["storage"], "node": _str(r.get("node")), "type": r.get("plugintype"),
            "status": r.get("status"), "shared": bool(r.get("shared")),
            "disk": r.get("disk", 0), "maxdisk": r.get("maxdisk"), "content": r.get("content"),
            "contents": _contents(r.get("content")),
            "used": used, "total": total,
            "free": total - used if used is not None and total is not None else None,
            "active": r.get("status") == "available",
            "nodes": sorted(carried.get(r["storage"], ())),
        })
    return sorted(out, key=lambda s: (s["storage"] or "", s["node"] or ""))


def _name(volid: str) -> str:
    """`local:iso/debian.iso` -> `debian.iso` ; `ceph:vm-100-disk-0` -> `vm-100-disk-0`."""
    return volid.split(":", 1)[-1].rsplit("/", 1)[-1]


def _iso(ts: int | None) -> str | None:
    """Date ISO 8601 en UTC, ou None si l'horodatage est absent ou hors limites."""
    if not ts or ts < 0:
        return None
    try:
        return datetime.fromtimestamp(ts, timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def shape_volumes(data) -> list[dict]:
    """Volumes d'un stockage : une entrée illisible (sans `volid`) est ignorée, pas fatale."""
    out = []
    for v in data if isinstance(data, list) else []:
        if not isinstance(v, dict) or not isinstance(v.get("volid"), str) or not v["volid"]:
            continue
        ctime = _int(v.get("ctime"))
        out.append({
            "volid": v["volid"], "name": _name(v["volid"]), "content": _str(v.get("content")),
            "format": _str(v.get("format")), "size": _int(v.get("size")),
            "ctime": ctime, "date": _iso(ctime),
            "vmid": _int(v.get("vmid")), "notes": _str(v.get("notes")), "protected": bool(v.get("protected")),
        })
    return sorted(out, key=lambda v: (v["content"] or "", v["name"], v["volid"]))
