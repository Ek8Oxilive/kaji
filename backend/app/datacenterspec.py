"""Options du datacenter Proxmox (Datacenter → Options et notes) : lecture tolérante et écriture en liste blanche (lot #150).

Champs gérés : `keyboard`, `language`, `console`, `description` (notes du datacenter), `mac_prefix`, `migration` (`type`, `network`), `max_workers`, `email_from`, `http_proxy`,
`next_id` (plage des identifiants libres : `lower`, `upper`), `tag_style` (`shape`, `ordering`, `case_sensitive`, `color_map`),
`registered_tags` (étiquettes réservées à `Sys.Modify`), `user_tag_access` (`user_allow`, `user_allow_list`) et `consent_text` (texte affiché avant la connexion).
Lus mais JAMAIS écrits (risque élevé, hors périmètre) : `ha`, `fencing`, `crs`, `bwlimit`, `replication`.
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
CLEARABLE = ("keyboard", "language", "console", "description", "mac_prefix", "migration", "max_workers", "email_from", "http_proxy", "next_id", "tag_style", "registered_tags", "user_tag_access", "consent_text")
READONLY = ("ha", "fencing", "crs", "bwlimit", "replication")
DELNAME = {"next_id": "next-id", "tag_style": "tag-style", "registered_tags": "registered-tags", "user_tag_access": "user-tag-access", "consent_text": "consent-text"}   # nom Kaji -> nom Proxmox (pour `delete=`)
KEY = {v: k for k, v in DELNAME.items()}                                                                                                      # nom Proxmox -> clé lue
TAGNAME = re.compile(r"^[a-z0-9_][a-z0-9_\-+.]{0,63}$")
USER_ALLOW = ("none", "list", "existing", "free")
MAX_TAGS = 100
MAX_CONSENT = 3000
ID_MIN, ID_MAX = 100, 999_999_999
SHAPES = ("full", "circle", "dense", "none")
ORDERINGS = ("config", "alphabetical")
TAG = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.+\-]{0,31}$")
HEX6 = re.compile(r"^[0-9A-Fa-f]{6}$")
MAX_COLORS = 50


def _choice(v, allowed):
    return v if isinstance(v, str) and v in allowed else None


def _props(v) -> dict:
    """Une chaîne de propriétés Proxmox (`a=1,b=2`) ou un objet, selon la version."""
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        return dict(p.partition("=")[::2] for p in v.split(",") if "=" in p)
    return {}


def _int_in(v, lo: int, hi: int):
    if isinstance(v, bool):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


def parse_next_id(v) -> dict:
    d = _props(v)
    return {"lower": _int_in(d.get("lower"), ID_MIN, ID_MAX), "upper": _int_in(d.get("upper"), ID_MIN, ID_MAX)}


def parse_color_map(v) -> list[dict]:
    """`tag:couleur[:couleur-du-texte];…` -> liste normalisée (couleurs en minuscules). Une entrée de forme inattendue est écartée."""
    out: list[dict] = []
    for e in (v.split(";") if isinstance(v, str) else []):
        parts = e.split(":")
        if len(parts) in (2, 3) and TAG.fullmatch(parts[0]) and HEX6.fullmatch(parts[1]) and (len(parts) == 2 or HEX6.fullmatch(parts[2])):
            out.append({"tag": parts[0], "color": parts[1].lower(), "text": parts[2].lower() if len(parts) == 3 else None})
    return out[:MAX_COLORS]


def parse_tag_style(v) -> dict:
    d = _props(v)
    cs = d.get("case-sensitive")
    return {"shape": _choice(d.get("shape"), SHAPES), "ordering": _choice(d.get("ordering"), ORDERINGS),
            "case_sensitive": True if cs is True or str(cs).lower() in ("1", "true", "yes", "on") else None, "color_map": parse_color_map(d.get("color-map"))}


def parse_tag_list(v) -> list[str]:
    """`a;b;c` (chaîne) ou liste -> étiquettes valides en minuscules, sans doublon, 100 au plus ; les valeurs de forme inattendue sont écartées."""
    items = v.split(";") if isinstance(v, str) else (v if isinstance(v, list) else [])
    out: list[str] = []
    for x in items:
        x = x.strip().lower() if isinstance(x, str) else ""
        if TAGNAME.fullmatch(x) and x not in out:
            out.append(x)
    return out[:MAX_TAGS]


def parse_user_tag_access(v) -> dict:
    d = _props(v)
    return {"user_allow": _choice(d.get("user-allow"), USER_ALLOW), "user_allow_list": parse_tag_list(d.get("user-allow-list"))}


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
        "next_id": parse_next_id(r.get("next-id")), "tag_style": parse_tag_style(r.get("tag-style")),
        "registered_tags": parse_tag_list(r.get("registered-tags")), "user_tag_access": parse_user_tag_access(r.get("user-tag-access")),
        "consent_text": _t(r.get("consent-text"), MAX_CONSENT),
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


class NextIdIn(BaseModel):
    lower: StrictInt | None = Field(default=None, ge=ID_MIN, le=ID_MAX)
    upper: StrictInt | None = Field(default=None, ge=ID_MIN, le=ID_MAX)


class ColorIn(BaseModel):
    tag: str = Field(max_length=32)
    color: str = Field(max_length=6)
    text: str | None = Field(default=None, max_length=6, description="Couleur du texte (facultative)")

    @field_validator("tag")
    @classmethod
    def _tag(cls, v):
        if not TAG.fullmatch(v):
            raise ValueError("Étiquette invalide (lettres, chiffres, _ . + -, 32 caractères au plus)")
        return v

    @field_validator("color", "text")
    @classmethod
    def _hex(cls, v):
        if v is None or v == "":
            return None
        if not HEX6.fullmatch(v):
            raise ValueError("Couleur invalide (6 chiffres hexadécimaux, sans #)")
        return v.lower()


class TagStyleIn(BaseModel):
    shape: Literal[SHAPES] | None = None                                          # type: ignore[valid-type]
    ordering: Literal[ORDERINGS] | None = None                                    # type: ignore[valid-type]
    case_sensitive: StrictBool | None = None
    color_map: list[ColorIn] | None = Field(default=None, max_length=MAX_COLORS, description="Remplace toute la table des couleurs ; liste vide = la retirer")

    @field_validator("color_map")
    @classmethod
    def _unique(cls, v):
        if v is not None and len({c.tag.lower() for c in v}) != len(v):
            raise ValueError("Étiquette en double dans les couleurs")
        return v


class UserTagAccessIn(BaseModel):
    user_allow: Literal[USER_ALLOW] | None = None                                 # type: ignore[valid-type]
    user_allow_list: list[str] | None = Field(default=None, max_length=MAX_TAGS, description="Étiquettes permises quand user_allow vaut « list »")

    @field_validator("user_allow_list")
    @classmethod
    def _lst(cls, v):
        if v is None:
            return v
        out = [x.strip().lower() for x in v]
        if any(not TAGNAME.fullmatch(x) for x in out):
            raise ValueError("Étiquette invalide (minuscules, chiffres, _ . + -, 64 caractères au plus)")
        return list(dict.fromkeys(out))


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
    next_id: NextIdIn | None = None
    tag_style: TagStyleIn | None = None
    registered_tags: list[str] | None = Field(default=None, max_length=MAX_TAGS, description="Liste vide = retirer le réglage")
    user_tag_access: UserTagAccessIn | None = None
    consent_text: str | None = Field(default=None, max_length=MAX_CONSENT)
    clear: list[Literal[CLEARABLE]] = Field(default=[], max_length=14)             # type: ignore[valid-type]
    digest: str | None = Field(default=None, max_length=64, description="Empreinte lue par GET ; refus (409) si l'état a changé depuis")
    confirm: StrictBool = False
    dry_run: StrictBool = False

    @field_validator("description")
    @classmethod
    def _desc(cls, v):
        if v is not None and not TEXT_OK.fullmatch(v):
            raise ValueError("Caractère de contrôle interdit")
        return v

    @field_validator("registered_tags")
    @classmethod
    def _rtags(cls, v):
        if v is None:
            return v
        out = [x.strip().lower() for x in v]
        if any(not TAGNAME.fullmatch(x) for x in out):
            raise ValueError("Étiquette invalide (minuscules, chiffres, _ . + -, 64 caractères au plus)")
        return list(dict.fromkeys(out))

    @field_validator("consent_text")
    @classmethod
    def _consent(cls, v):
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
    if body.next_id is not None and (body.next_id.lower is not None or body.next_id.upper is not None):
        cur = current.get("next_id") or {}
        lo = body.next_id.lower if body.next_id.lower is not None else cur.get("lower")
        up = body.next_id.upper if body.next_id.upper is not None else cur.get("upper")
        if lo is not None and up is not None and lo >= up:
            raise ValueError("« lower » doit être inférieur à « upper »")
        p["next-id"] = ",".join(f"{k}={v}" for k, v in (("lower", lo), ("upper", up)) if v is not None)
    ts = body.tag_style
    if ts is not None and (ts.shape is not None or ts.ordering is not None or ts.case_sensitive is not None or ts.color_map is not None):
        cur = current.get("tag_style") or {}
        shape, ordering = ts.shape or cur.get("shape"), ts.ordering or cur.get("ordering")
        cs = ts.case_sensitive if ts.case_sensitive is not None else bool(cur.get("case_sensitive"))
        cmap = [c.model_dump() for c in ts.color_map] if ts.color_map is not None else (cur.get("color_map") or [])
        parts = ([f"shape={shape}"] if shape else []) + ([f"ordering={ordering}"] if ordering else []) + (["case-sensitive=1"] if cs else []) \
            + (["color-map=" + ";".join(c["tag"] + ":" + c["color"] + (":" + c["text"] if c.get("text") else "") for c in cmap)] if cmap else [])
        if parts:
            p["tag-style"] = ",".join(parts)
        elif "tag_style" not in delete:
            delete.append("tag_style")                                  # plus aucun sous-réglage : on retire le réglage
    if body.registered_tags is not None:
        if body.registered_tags:
            p["registered-tags"] = ";".join(body.registered_tags)
        elif "registered_tags" not in delete:
            delete.append("registered_tags")                            # liste vide : on retire le réglage
    uta = body.user_tag_access
    if uta is not None and (uta.user_allow is not None or uta.user_allow_list is not None):
        cur = current.get("user_tag_access") or {}
        allow = uta.user_allow or cur.get("user_allow")
        lst = uta.user_allow_list if uta.user_allow_list is not None else (cur.get("user_allow_list") or [])
        if allow is None:
            raise ValueError("Précise « user_allow » (none, list, existing ou free)")
        if allow == "list" and not lst:
            raise ValueError("« list » exige au moins une étiquette dans « user_allow_list »")
        p["user-tag-access"] = f"user-allow={allow}" + (f",user-allow-list={';'.join(lst)}" if allow == "list" else "")
    if body.consent_text is not None:
        if body.consent_text.strip():
            p["consent-text"] = body.consent_text
        elif "consent_text" not in delete:
            delete.append("consent_text")                               # texte vide : on retire le réglage
    clash = [k for k in delete if DELNAME.get(k, k) in p]
    if clash:
        raise ValueError("Réglage à la fois modifié et retiré")
    if not p and not delete:
        raise ValueError("Aucune modification demandée")
    return p, delete, []
