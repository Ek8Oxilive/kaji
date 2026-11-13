"""Notifications Proxmox (Datacenter → Notifications : cibles et règles) en LECTURE : mise en forme tolérante, en liste blanche, textes bornés (lot #151, étape 1).

AUCUN secret ne sort : ni le mot de passe SMTP, ni le jeton Gotify, ni les valeurs des en-têtes et secrets d'un webhook (on n'en garde que les NOMS), ni son corps (seulement « défini »).
Une cible intégrée (`origin` = `builtin`, ex. `mail-to-root`) est signalée : elle n'est pas supprimable.
"""
import re

from .networkspec import _b, _int, _rows, _t

NAME = re.compile(r"^[A-Za-z][A-Za-z0-9._\-]{1,63}$")
TARGET_TYPES = ("sendmail", "smtp", "gotify", "webhook")
ORIGINS = ("user-created", "builtin", "modified-builtin")
SEVERITIES = ("info", "notice", "warning", "error", "unknown")
MODES = ("all", "any")
SMTP_MODES = ("insecure", "starttls", "tls")
METHODS = ("post", "put", "get")
HEADER_NAME = re.compile(r"^[A-Za-z0-9\-]{1,64}$")
FIELD = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
MAX_ITEMS = 100


def _name(v):
    return v if isinstance(v, str) and NAME.fullmatch(v) else None


def _list(v, n: int = 200) -> list[str]:
    """Liste de textes courts (Proxmox renvoie un tableau, ou une chaîne séparée par des virgules selon la version)."""
    items = v if isinstance(v, list) else v.split(",") if isinstance(v, str) else []
    return [t for x in items[:MAX_ITEMS] if isinstance(x, str) and (t := _t(x.strip(), n))]


def _name_of(x) -> str | None:
    """Nom d'une entrée d'en-tête ou de secret : chaîne de propriétés `name=X,value=…` (format du schéma de Proxmox 9), objet `{name}` ou ancien `nom=valeur`. La valeur n'est jamais gardée."""
    if isinstance(x, dict):
        x = x.get("name")
        n = x.strip() if isinstance(x, str) else ""
    elif isinstance(x, str):
        named = [v for k, _, v in (p.partition("=") for p in x.split(",")) if k.strip() == "name"]
        n = (named[0] if named else x.partition("=")[0]).strip()
    else:
        return None
    return n if HEADER_NAME.fullmatch(n) else None


def _names_of(v) -> list[str]:
    """Noms seulement d'une liste d'en-têtes ou de secrets d'un webhook : la valeur peut être un jeton, elle ne sort jamais."""
    items = v if isinstance(v, list) else v.split(",") if isinstance(v, str) else []
    return [n for x in items[:MAX_ITEMS] if (n := _name_of(x))]


def shape_targets(raw) -> list[dict]:
    out = []
    for r in _rows(raw):
        n, t = _name(r.get("name")), r.get("type")
        if n and t in TARGET_TYPES:
            origin = r.get("origin") if r.get("origin") in ORIGINS else None
            out.append({"name": n, "type": t, "disable": bool(_b(r.get("disable"))), "comment": _t(r.get("comment"), 500), "origin": origin, "builtin": origin == "builtin"})
    return sorted(out, key=lambda x: x["name"])


def shape_endpoint(raw, typ: str) -> dict | None:
    """Un point de terminaison, avec les champs de SON type seulement. `password`, `token`, valeurs d'en-têtes et de secrets : jamais."""
    n = _name(raw.get("name")) if isinstance(raw, dict) else None
    if not n:
        return None
    origin = raw.get("origin") if raw.get("origin") in ORIGINS else None
    out = {"name": n, "type": typ, "disable": bool(_b(raw.get("disable"))), "comment": _t(raw.get("comment"), 500), "origin": origin, "builtin": origin == "builtin"}
    if typ in ("sendmail", "smtp"):
        out.update({"author": _t(raw.get("author"), 120), "from_address": _t(raw.get("from-address"), 254), "mailto": _list(raw.get("mailto"), 254), "mailto_user": _list(raw.get("mailto-user"), 128)})
    if typ == "smtp":
        out.update({"server": _t(raw.get("server"), 253), "port": _int(raw.get("port")), "mode": raw.get("mode") if raw.get("mode") in SMTP_MODES else None, "username": _t(raw.get("username"), 128)})
    if typ == "gotify":
        out["server"] = _t(raw.get("server"), 300)
    if typ == "webhook":
        out.update({"url": _t(raw.get("url"), 500), "method": raw.get("method") if raw.get("method") in METHODS else None, "header_names": _names_of(raw.get("header")),
                    "secret_names": _names_of(raw.get("secret")), "body_set": bool(raw.get("body"))})
    return out


def shape_matchers(raw) -> list[dict]:
    out = []
    for r in _rows(raw):
        n = _name(r.get("name"))
        if not n:
            continue
        origin = r.get("origin") if r.get("origin") in ORIGINS else None
        out.append({"name": n, "disable": bool(_b(r.get("disable"))), "invert": bool(_b(r.get("invert-match"))), "mode": r.get("mode") if r.get("mode") in MODES else "all",
                    "match_field": _list(r.get("match-field")), "match_severity": [s for s in _list(r.get("match-severity"), 20) if s in SEVERITIES], "match_calendar": _list(r.get("match-calendar")),
                    "targets": [t for t in _list(r.get("target"), 64) if NAME.fullmatch(t)], "comment": _t(r.get("comment"), 500), "origin": origin, "builtin": origin == "builtin"})
    return sorted(out, key=lambda x: x["name"])


def shape_fields(raw) -> list[str]:
    return sorted({n for r in _rows(raw) if isinstance(n := r.get("name"), str) and FIELD.fullmatch(n)})[:MAX_ITEMS]


def shape_field_values(raw) -> list[dict]:
    out = [{"field": f, "value": _t(r.get("value"), 120), "comment": _t(r.get("comment"), 200)} for r in _rows(raw) if isinstance(f := r.get("field"), str) and FIELD.fullmatch(f)]
    return out[:500]
