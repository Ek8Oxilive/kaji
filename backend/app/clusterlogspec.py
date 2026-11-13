"""Journal du cluster (Datacenter → Journal du cluster) : mise en forme de `GET /cluster/log`. Lecture seule.

Tout ce qui vient de Proxmox est traité comme une donnée non fiable : types vérifiés, caractères de contrôle remplacés, longueurs bornées.
"""
import re

MAX_ENTRIES = 500
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _text(v, limit: int) -> str:
    return _CONTROL.sub(" ", v)[:limit] if isinstance(v, str) else ""


def _int(v, lo: int, hi: int):
    return v if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi else None


def shape_log(raw) -> list[dict]:
    """Entrées valides seulement, plus récentes d'abord. `pri` : gravité syslog 0 (urgence) à 7 (debug), 6 (info) si illisible."""
    out = []
    for r in (raw if isinstance(raw, list) else [])[:MAX_ENTRIES]:
        if not isinstance(r, dict):
            continue
        pri = _int(r.get("pri"), 0, 7)
        out.append({"time": _int(r.get("time"), 0, 4_102_444_800), "pri": 6 if pri is None else pri, "tag": _text(r.get("tag"), 40), "node": _text(r.get("node"), 64),
                    "user": _text(r.get("user"), 80) or None, "pid": _int(r.get("pid"), 0, 4_194_304), "msg": _text(r.get("msg"), 500)})
    return sorted(out, key=lambda e: e["time"] or 0, reverse=True)
