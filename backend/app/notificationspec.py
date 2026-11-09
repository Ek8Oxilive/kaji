"""Notifications Proxmox (Datacenter → Notifications) : mise en forme en liste blanche des CIBLES (endpoints : sendmail, SMTP, Gotify, webhook) et des RÈGLES (matchers) (lot #151, lecture).

Rien n'est transmis tel quel : on ne garde que des champs connus, bornés, sans caractère de contrôle. Les SECRETS ne sortent jamais : le mot de passe SMTP, le jeton Gotify, les valeurs des
en-têtes et des secrets d'un webhook et son corps ne sont pas renvoyés (seuls les NOMS d'en-têtes et de secrets, et « corps défini »). L'adresse d'un webhook est nettoyée : sans identifiants
(`user:mdp@`), sans paramètres (`?token=…`) ni fragment.
"""
import re
from urllib.parse import urlsplit

from .networkspec import _b, _t

NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,62}[A-Za-z0-9]$|^[A-Za-z]$")          # `pve-configid`
TYPES = ("sendmail", "gotify", "smtp", "webhook")
ORIGINS = ("builtin", "user-created", "modified-builtin")
MATCHER_MODES = ("all", "any")
SMTP_MODES = ("insecure", "starttls", "tls")
HTTP_METHODS = ("post", "put", "get")
_HEADER_NAME = re.compile(r"[A-Za-z0-9\-_.]{1,100}")
MAX_ROWS = 200


def _name(v) -> str | None:
    return v if isinstance(v, str) and NAME.fullmatch(v) else None


def _items(v, n: int = 50, w: int = 200) -> list[str]:
    """Liste de textes bornés (Proxmox renvoie un tableau, ou parfois un texte séparé par des virgules)."""
    if isinstance(v, str):
        v = v.split(",")
    return [t for x in (v if isinstance(v, list) else [])[:n] if (t := _t(x, w))]


def _num(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 65535 else None


def safe_url(v) -> str | None:
    """`schéma://hôte[:port]/chemin` : ni identifiants, ni paramètres, ni fragment (ils peuvent porter un jeton)."""
    if not isinstance(v, str) or len(v) > 2048:
        return None
    try:
        u = urlsplit(v.strip())
        host = u.hostname
        port = f":{u.port}" if u.port else ""
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or not host:
        return None
    return _t(f"{u.scheme}://{'[' + host + ']' if ':' in host else host}{port}{u.path}", 300)


def _header_names(v) -> list[str]:
    """Noms seulement : `name=X,value=<base64>` -> `X` (la valeur peut être un jeton)."""
    out = []
    for e in (v if isinstance(v, list) else [])[:50]:
        parts = e.split(",") if isinstance(e, str) else []
        name = next((p[5:] for p in parts if p.startswith("name=")), None)                # seul le NOM est gardé, jamais `value=`
        if name and _HEADER_NAME.fullmatch(name):
            out.append(name)
    return out


def shape_target(raw) -> dict | None:
    if not isinstance(raw, dict) or (name := _name(raw.get("name"))) is None or raw.get("type") not in TYPES:
        return None
    return {"name": name, "type": raw["type"], "comment": _t(raw.get("comment"), 200), "disable": bool(_b(raw.get("disable"))),
            "origin": raw.get("origin") if raw.get("origin") in ORIGINS else None}


def shape_targets(raw) -> list[dict]:
    rows = [s for r in (raw[:MAX_ROWS] if isinstance(raw, list) else []) if (s := shape_target(r))]
    return sorted(rows, key=lambda r: r["name"])


def shape_endpoint(raw, typ: str) -> dict | None:
    """Une cible d'un type donné : champs communs + champs propres au type. Aucun secret."""
    if typ not in TYPES or not isinstance(raw, dict) or (name := _name(raw.get("name"))) is None:
        return None
    out = {"name": name, "type": typ, "comment": _t(raw.get("comment"), 200), "disable": bool(_b(raw.get("disable"))),
           "origin": raw.get("origin") if raw.get("origin") in ORIGINS else None}
    if typ == "sendmail":
        out.update({"author": _t(raw.get("author"), 120), "from_address": _t(raw.get("from-address"), 254),
                    "mailto": _items(raw.get("mailto"), 50, 254), "mailto_user": _items(raw.get("mailto-user"), 50, 64)})
    elif typ == "smtp":
        out.update({"server": _t(raw.get("server"), 253), "port": _num(raw.get("port")), "mode": raw.get("mode") if raw.get("mode") in SMTP_MODES else None,
                    "username": _t(raw.get("username"), 128), "from_address": _t(raw.get("from-address"), 254), "author": _t(raw.get("author"), 120),
                    "mailto": _items(raw.get("mailto"), 50, 254), "mailto_user": _items(raw.get("mailto-user"), 50, 64)})
    elif typ == "gotify":
        out.update({"server": safe_url(raw.get("server"))})                               # le jeton (`token`) n'est ni relu ni renvoyé
    else:
        out.update({"url": safe_url(raw.get("url")), "method": raw.get("method") if raw.get("method") in HTTP_METHODS else None,
                    "header_names": _header_names(raw.get("header")), "secret_names": _header_names(raw.get("secret")), "body_set": bool(raw.get("body"))})
    return out


def shape_endpoints(raw, typ: str) -> list[dict]:
    rows = [s for r in (raw[:MAX_ROWS] if isinstance(raw, list) else []) if (s := shape_endpoint(r, typ))]
    return sorted(rows, key=lambda r: r["name"])


def shape_matcher(raw) -> dict | None:
    if not isinstance(raw, dict) or (name := _name(raw.get("name"))) is None:
        return None
    return {"name": name, "comment": _t(raw.get("comment"), 200), "disable": bool(_b(raw.get("disable"))),
            "mode": raw.get("mode") if raw.get("mode") in MATCHER_MODES else "all", "invert_match": bool(_b(raw.get("invert-match"))),
            "match_field": _items(raw.get("match-field")), "match_severity": _items(raw.get("match-severity"), 10, 20),
            "match_calendar": _items(raw.get("match-calendar"), 20, 200), "target": [t for t in _items(raw.get("target"), 50, 64) if NAME.fullmatch(t)],
            "origin": raw.get("origin") if raw.get("origin") in ORIGINS else None}


def shape_matchers(raw) -> list[dict]:
    rows = [s for r in (raw[:MAX_ROWS] if isinstance(raw, list) else []) if (s := shape_matcher(r))]
    return sorted(rows, key=lambda r: r["name"])


def shape_fields(raw) -> list[str]:
    """Noms des champs sur lesquels une règle peut porter (`type`, `hostname`…)."""
    names = [_t(r.get("name"), 64) if isinstance(r, dict) else _t(r, 64) for r in (raw[:MAX_ROWS] if isinstance(raw, list) else [])]
    return sorted({n for n in names if n and re.fullmatch(r"[A-Za-z0-9_.\-]+", n)})


def shape_field_values(raw) -> list[dict]:
    rows = []
    for r in (raw[:1000] if isinstance(raw, list) else []):
        if isinstance(r, dict) and (f := _t(r.get("field"), 64)) and (v := _t(r.get("value"), 200)):
            rows.append({"field": f, "value": v, "comment": _t(r.get("comment"), 200)})
    return rows
