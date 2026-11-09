"""Options du datacenter Proxmox (Datacenter → Options et notes) : lecture tolérante et écriture en liste blanche (lot #150).

Champs gérés : `keyboard`, `language`, `console`, `description` (notes du datacenter), `mac_prefix`, `migration` (`type`, `network`), `max_workers`, `email_from`, `http_proxy`.
Lus mais JAMAIS écrits (risque élevé, hors périmètre) : `ha`, `fencing`, `crs`, `bwlimit`, `next-id`, `tag-style`, `replication`.
Le `PUT /cluster/options` de Proxmox n'a PAS de `digest` : Kaji calcule le sien (empreinte des valeurs lues) pour refuser, en 409, une modification faite sur un état périmé.
Rien n'est transmis sans validation ; un champ inconnu est ignoré ; `http_proxy` : `http://hôte[:port]`, sans identifiants, ni boucle locale, ni adresse non spécifiée, de liaison locale ou multicast.
"""
import hashlib
import ipaddress
import json
import re
from typing import Literal

from pydantic import BaseModel, Field, StrictBool, StrictInt, field_validator

from .networkspec import _t

KEYBOARDS = ("de", "de-ch", "da", "en-gb", "en-us", "es", "fi", "fr", "fr-be", "fr-ca", "fr-ch", "hu", "is", "it", "ja", "lt", "mk", "nl", "no", "pl", "pt", "pt-br", "sv", "sl", "tr")
LANGUAGES = ("ar", "ca", "da", "de", "en", "es", "eu", "fa", "fr", "hr", "he", "it", "ja", "ka", "kr", "nb", "nl", "nn", "pl", "pt_BR", "ru", "sl", "sv", "tr", "ukr", "zh_CN", "zh_TW")
CONSOLES = ("applet", "vv", "html5", "xtermjs")
MAC = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){2}$")
EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,190}$")
PROXY = re.compile(r"^http://(?P<host>[A-Za-z0-9.\-]{1,253}|\[[0-9A-Fa-f:]{2,39}\])(:(?P<port>[0-9]{1,5}))?/?$")
TEXT_OK = re.compile(r"[^\x00-\x08\x0b\x0c\x0d\x0e-\x1f\x7f]*")                  # notes : \n et \t permis, tout autre caractère de contrôle refusé
MAX_NOTES = 65536
CLEARABLE = ("keyboard", "language", "console", "description", "mac_prefix", "migration", "max_workers", "email_from", "http_proxy")
READONLY = ("ha", "fencing", "crs", "bwlimit", "next-id", "tag-style", "replication")


def _choice(v, allowed):
    return v if isinstance(v, str) and v in allowed else None


def parse_migration(v) -> dict:
    """`migration` : objet (`{type, network}`) ou chaîne de propriétés (`type=secure,network=10.0.0.0/24`) selon la version."""
    d: dict = {}
    if isinstance(v, dict):
        d = v
    elif isinstance(v, str):
        d = dict(p.partition("=")[::2] for p in v.split(",") if "=" in p)
    net = d.get("network")
    try:
        net = str(ipaddress.ip_network(net, strict=True)) if isinstance(net, str) else None
    except ValueError:
        net = None
    return {"type": _choice(d.get("type"), ("secure", "insecure")), "network": net}


def shape_options(raw) -> dict:
    r = raw if isinstance(raw, dict) else {}
    out = {
        "keyboard": _choice(r.get("keyboard"), KEYBOARDS), "language": _choice(r.get("language"), LANGUAGES), "console": _choice(r.get("console"), CONSOLES),
        "description": _t(r.get("description"), MAX_NOTES), "mac_prefix": r["mac_prefix"] if isinstance(r.get("mac_prefix"), str) and MAC.fullmatch(r["mac_prefix"]) else None,
        "migration": parse_migration(r.get("migration")),
        "max_workers": r["max_workers"] if isinstance(r.get("max_workers"), int) and not isinstance(r.get("max_workers"), bool) and 1 <= r["max_workers"] <= 1_000_000 else None,
        "email_from": r["email_from"] if isinstance(r.get("email_from"), str) and EMAIL.fullmatch(r["email_from"]) else None,
        "http_proxy": r["http_proxy"] if isinstance(r.get("http_proxy"), str) and PROXY.fullmatch(r["http_proxy"]) else None,
    }
    if out["migration"]["type"] is None and r.get("migration_unsecure") in (1, True, "1"):         # ancien réglage, remplacé par `migration`
        out["migration"]["type"] = "insecure"
    out["readonly"] = {k: _t(json.dumps(r[k], sort_keys=True) if isinstance(r.get(k), (dict, list)) else str(r[k]), 200) for k in READONLY if r.get(k) is not None}
    return out


def digest_of(shaped: dict) -> str:
    """Empreinte des valeurs lues (propre à Kaji : Proxmox n'a pas de `digest` pour ces options)."""
    return hashlib.sha256(json.dumps(shaped, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:40]


def check_proxy(v: str) -> str:
    m = PROXY.fullmatch(v)
    if not m:
        raise ValueError("Proxy invalide (attendu : http://hôte[:port], sans identifiants ni chemin)")
    host, port = m.group("host"), m.group("port")
    if port is not None and not 1 <= int(port) <= 65535:
        raise ValueError("Port invalide")
    bare = host.strip("[]")
    try:
        ip = ipaddress.ip_address(bare)
    except ValueError:
        if bare.lower() == "localhost" or bare.lower().endswith(".localhost"):
            raise ValueError("Adresse locale refusée")
        return v
    if ip.is_loopback or ip.is_unspecified or ip.is_link_local or ip.is_multicast:
        raise ValueError("Adresse locale refusée")
    return v


class MigrationIn(BaseModel):
    type: Literal["secure", "insecure"] | None = None
    network: str | None = Field(default=None, max_length=43, description="CIDR ; chaîne vide = retirer le réseau dédié")

    @field_validator("network")
    @classmethod
    def _net(cls, v):
        if v in (None, ""):
            return v
        try:
            return str(ipaddress.ip_network(v, strict=True))
        except ValueError:
            raise ValueError("Réseau invalide (CIDR attendu, sans bits d'hôte)")


class DatacenterOptions(BaseModel):
    keyboard: Literal[KEYBOARDS] | None = None                                    # type: ignore[valid-type]
    language: Literal[LANGUAGES] | None = None                                    # type: ignore[valid-type]
    console: Literal[CONSOLES] | None = None                                      # type: ignore[valid-type]
    description: str | None = Field(default=None, max_length=MAX_NOTES)
    mac_prefix: str | None = None
    migration: MigrationIn | None = None
    max_workers: StrictInt | None = Field(default=None, ge=1, le=64)
    email_from: str | None = Field(default=None, max_length=254)
    http_proxy: str | None = Field(default=None, max_length=300)
    clear: list[Literal[CLEARABLE]] = Field(default=[], max_length=9)             # type: ignore[valid-type]
    digest: str | None = Field(default=None, max_length=64, description="Empreinte lue par GET ; refus (409) si l'état a changé depuis")
    confirm: StrictBool = False
    dry_run: StrictBool = False

    @field_validator("description")
    @classmethod
    def _desc(cls, v):
        if v is not None and not TEXT_OK.fullmatch(v):
            raise ValueError("Caractère de contrôle interdit")
        return v

    @field_validator("mac_prefix")
    @classmethod
    def _mac(cls, v):
        if v is None:
            return v
        if not MAC.fullmatch(v):
            raise ValueError("Préfixe MAC invalide (attendu XX:XX:XX)")
        if int(v[:2], 16) & 1:
            raise ValueError("Préfixe multicast refusé (le premier octet doit être pair)")
        return v.upper()

    @field_validator("email_from")
    @classmethod
    def _mail(cls, v):
        if v is not None and not EMAIL.fullmatch(v):
            raise ValueError("Adresse e-mail invalide")
        return v

    @field_validator("http_proxy")
    @classmethod
    def _proxy(cls, v):
        return check_proxy(v) if v is not None else v


def build(body: DatacenterOptions, current: dict) -> tuple[dict, list[str], list[str]]:
    """`(paramètres Proxmox, réglages à retirer, avertissements)`. `migration` est une chaîne de propriétés : fusionnée avec l'état lu pour ne rien perdre."""
    p: dict = {}
    for k in ("keyboard", "language", "console", "description", "mac_prefix", "max_workers", "email_from", "http_proxy"):
        v = getattr(body, k)
        if v is not None:
            p[k] = v
    delete = list(dict.fromkeys(body.clear))
    if body.migration is not None and (body.migration.type is not None or body.migration.network is not None):
        cur = current.get("migration") or {}
        typ = body.migration.type or cur.get("type") or "secure"
        net = cur.get("network") if body.migration.network is None else (body.migration.network or None)
        p["migration"] = f"type={typ}" + (f",network={net}" if net else "")
    clash = [k for k in delete if k in p]
    if clash:
        raise ValueError("Réglage à la fois modifié et retiré")
    if not p and not delete:
        raise ValueError("Aucune modification demandée")
    return p, delete, []
