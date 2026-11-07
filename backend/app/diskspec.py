"""Disques d'un nœud (lecture seule) : disques et partitions, groupes LVM, pools LVM-thin, répertoires, ZFS, SMART.

Mise en forme tolérante : champs en liste blanche, textes bornés, valeurs absurdes (`"N/A"`, négatifs) → `null`. Le texte SMART
brut est borné et n'est jamais interprété. Les numéros de série et identifiants WWN ne sont pas repris.
"""
import re

from .storagespec import _int, _str

DEVICE = re.compile(r"/dev/[A-Za-z0-9]{1,30}")          # disque ou partition, sans sous-dossier (`fullmatch`)
MAX_ROWS = 300
MAX_SMART_TEXT = 12000
SMART_TYPES = {"text", "ata"}


def _t(v, n: int = 120) -> str | None:
    s = _str(v)
    return s[:n] if s is not None else None


def _rows(raw) -> list[dict]:
    return [r for r in raw if isinstance(r, dict)][:MAX_ROWS] if isinstance(raw, list) else []


def _pct(v) -> int | None:
    n = _int(v)
    return n if n is not None and 0 <= n <= 100 else None


def shape_disks(raw) -> list[dict]:
    """Disques physiques avec leurs partitions (`include-partitions`). Une partition se rattache au disque dont elle porte le préfixe."""
    disks, parts = [], []
    for r in _rows(raw):
        dev = _str(r.get("devpath"))
        if not dev or not DEVICE.fullmatch(dev):
            continue
        row = {"device": dev, "size": _int(r.get("size")), "used": _t(r.get("used"), 40), "gpt": bool(r.get("gpt")), "osd": _int(r.get("osdid")) not in (None, -1),
               "model": _t(r.get("model"), 80), "type": _t(r.get("type"), 20), "health": _t(r.get("health"), 40), "wearout": _pct(r.get("wearout"))}
        (parts if row["type"] == "partition" else disks).append(row)
    out = []
    for d in sorted(disks, key=lambda d: d["device"]):
        # nvme0n1 -> nvme0n1p1 ; sda -> sda1 : le préfixe suffit, et seul un chiffre (ou « p » + chiffre) peut suivre
        mine = [p for p in parts if re.fullmatch(re.escape(d["device"]) + r"p?[0-9]+", p["device"])]
        out.append({**d, "partitions": [{"device": p["device"], "size": p["size"], "used": p["used"]} for p in sorted(mine, key=lambda p: p["device"])]})
    return out


def shape_lvm(raw) -> list[dict]:
    root = raw if isinstance(raw, dict) else {}
    out = []
    for vg in _rows(root.get("children")):
        name = _t(vg.get("name"), 60)
        if not name:
            continue
        out.append({"name": name, "size": _int(vg.get("size")), "free": _int(vg.get("free")), "volumes": _int(vg.get("lvcount")),
                    "devices": [d for d in (_t(c.get("name"), 80) for c in _rows(vg.get("children"))) if d]})
    return sorted(out, key=lambda v: v["name"])


def shape_lvmthin(raw) -> list[dict]:
    out = [{"name": _t(r.get("lv"), 60), "vg": _t(r.get("vg"), 60), "size": _int(r.get("lv_size")), "used": _int(r.get("used")),
            "metadata_size": _int(r.get("metadata_size")), "metadata_used": _int(r.get("metadata_used"))} for r in _rows(raw)]
    return sorted((p for p in out if p["name"]), key=lambda p: (p["vg"] or "", p["name"]))


def shape_directories(raw) -> list[dict]:
    out = [{"path": _t(r.get("path"), 200), "device": _t(r.get("device"), 80), "type": _t(r.get("type"), 20), "options": _t(r.get("options"), 120)} for r in _rows(raw)]
    return [d for d in out if d["path"]]


def shape_zfs(raw) -> list[dict]:
    out = [{"name": _t(r.get("name"), 80), "size": _int(r.get("size")), "alloc": _int(r.get("alloc")), "free": _int(r.get("free")),
            "health": _t(r.get("health"), 30), "fragmentation": _pct(r.get("frag"))} for r in _rows(raw)]
    return sorted((z for z in out if z["name"]), key=lambda z: z["name"])


def shape_smart(raw) -> dict:
    r = raw if isinstance(raw, dict) else {}
    kind = r.get("type") if r.get("type") in SMART_TYPES else "text"
    attrs = []
    for a in _rows(r.get("attributes")) if kind == "ata" else []:
        name = _t(a.get("name"), 60)
        if name:
            attrs.append({"id": _int(a.get("id")), "name": name, "value": _int(a.get("value")), "worst": _int(a.get("worst")),
                          "threshold": _int(a.get("threshold")), "raw": _t(a.get("raw"), 40), "failing": _t(a.get("fail"), 10) not in (None, "", "-")})
    text = _t(r.get("text"), MAX_SMART_TEXT)
    return {"health": _t(r.get("health"), 40), "type": kind, "wearout": _pct(r.get("wearout")), "attributes": attrs[:80], "text": text}
