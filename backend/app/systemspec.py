"""Système d'un nœud (lecture seule) : mise en forme tolérante des réponses de Proxmox.

Chaque rubrique est indépendante : une rubrique illisible ou interdite ne fait jamais échouer les autres. Seuls les champs
de la liste blanche sont repris, les textes libres sont bornés, rien n'est interprété. Les certificats sont renvoyés **sans**
leur contenu PEM. L'état d'un abonnement n'expose ni clé ni identifiant de serveur.
"""
import re
from datetime import datetime, timezone

from .servicespec import KNOWN, NO_STOP, risk
from .storagespec import _int, _str

MAX_ROWS = 500
MAX_TEXT = 300
SERVICE = re.compile(r"[A-Za-z0-9@._:-]{1,80}")
SYSLOG_MAX = 500


def _t(v, n: int = MAX_TEXT) -> str | None:
    s = _str(v)
    return s[:n] if s is not None else None


def _rows(raw) -> list[dict]:
    return [r for r in raw if isinstance(r, dict)][:MAX_ROWS] if isinstance(raw, list) else []


def _iso(ts) -> str | None:
    n = _int(ts)
    if n is None or n <= 0:
        return None
    try:
        return datetime.fromtimestamp(n, timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def shape_status(raw) -> dict:
    r = raw if isinstance(raw, dict) else {}
    return {"pveversion": _t(r.get("pveversion"), 120), "kernel": _t(r.get("current-kernel", {}).get("release") if isinstance(r.get("current-kernel"), dict) else None, 120),
            "uptime": _int(r.get("uptime")), "boot_mode": _t((r.get("boot-info") or {}).get("mode") if isinstance(r.get("boot-info"), dict) else None, 20)}


def shape_time(raw) -> dict:
    r = raw if isinstance(raw, dict) else {}
    return {"timezone": _t(r.get("timezone"), 80), "time": _iso(r.get("time")), "localtime": _iso(r.get("localtime"))}


def shape_dns(raw) -> dict:
    r = raw if isinstance(raw, dict) else {}
    return {"search": _t(r.get("search"), 255), "servers": [s for s in (_t(r.get("dns1"), 64), _t(r.get("dns2"), 64), _t(r.get("dns3"), 64)) if s]}


def shape_services(raw) -> list[dict]:
    out = []
    for r in _rows(raw):
        name = _str(r.get("name"))
        if not name or not SERVICE.fullmatch(name):
            continue
        out.append({"name": name, "description": _t(r.get("desc"), 120), "state": _t(r.get("state"), 30),
                    "active": _t(r.get("active-state"), 30), "enabled": _t(r.get("unit-state"), 30),
                    "manageable": name in KNOWN, "risk": risk(name), "stoppable": name not in NO_STOP})
    return sorted(out, key=lambda s: s["name"])


def shape_updates(raw) -> list[dict]:
    out = [{"package": _t(r.get("Package"), 120), "from": _t(r.get("OldVersion"), 80), "to": _t(r.get("Version"), 80),
            "title": _t(r.get("Title"), 160), "origin": _t(r.get("Origin"), 60)} for r in _rows(raw)]
    return sorted((u for u in out if u["package"]), key=lambda u: u["package"])


def shape_versions(raw) -> dict:
    rows = _rows(raw)
    key = [{"package": _t(r.get("Package"), 120), "version": _t(r.get("OldVersion") or r.get("Version"), 80)}
           for r in rows if _str(r.get("Package")) and (r.get("Package").startswith(("proxmox-ve", "pve-manager", "proxmox-kernel", "pve-kernel", "qemu-server", "pve-container", "ceph")))]
    return {"installed": len(rows), "key": sorted(key, key=lambda k: k["package"])}


def shape_repositories(raw) -> dict:
    r = raw if isinstance(raw, dict) else {}
    files = []
    for f in _rows(r.get("files")):
        repos = [{"types": [t for t in (f2.get("Types") or []) if isinstance(t, str)][:4], "uris": [u for u in (f2.get("URIs") or []) if isinstance(u, str)][:4],
                  "suites": [s for s in (f2.get("Suites") or []) if isinstance(s, str)][:4], "components": [c for c in (f2.get("Components") or []) if isinstance(c, str)][:6],
                  "enabled": bool(f2.get("Enabled"))} for f2 in _rows(f.get("repositories"))]
        files.append({"path": _t(f.get("path"), 200), "repositories": repos})
    return {"files": files, "errors": len(_rows(r.get("errors"))), "standard": [{"name": _t(s.get("name"), 60), "status": s.get("status") if isinstance(s.get("status"), int) and not isinstance(s.get("status"), bool) else None}
                                                                              for s in _rows(r.get("standard-repos"))]}


def shape_certificates(raw) -> list[dict]:
    return [{"file": _t(r.get("filename"), 80), "subject": _t(r.get("subject"), 300), "issuer": _t(r.get("issuer"), 300),
             "not_before": _iso(r.get("notbefore")), "not_after": _iso(r.get("notafter")), "fingerprint": _t(r.get("fingerprint"), 120),
             "san": [s for s in (r.get("san") or []) if isinstance(s, str)][:20]} for r in _rows(raw)]


def shape_disks(raw) -> list[dict]:
    out = []
    for r in _rows(raw):
        dev = _str(r.get("devpath"))
        if not dev or not re.fullmatch(r"/dev/[A-Za-z0-9/_.-]{1,60}", dev):
            continue
        w = r.get("wearout")
        out.append({"device": dev, "model": _t(r.get("model"), 80), "type": _t(r.get("type"), 20), "size": _int(r.get("size")),
                    "health": _t(r.get("health"), 40), "wearout": w if isinstance(w, (int, float)) and not isinstance(w, bool) and 0 <= w <= 100 else None,
                    "used": _t(r.get("used"), 40), "gpt": bool(r.get("gpt"))})
    return sorted(out, key=lambda d: d["device"])


def shape_subscription(raw) -> dict:
    r = raw if isinstance(raw, dict) else {}
    return {"status": _t(r.get("status"), 30)}


def shape_syslog(raw, limit: int) -> list[dict]:
    out = []
    for r in raw if isinstance(raw, list) else []:
        if isinstance(r, dict) and _int(r.get("n")) is not None:
            out.append({"n": _int(r.get("n")), "text": _t(r.get("t"), 1000) or ""})
    return out[:limit]
