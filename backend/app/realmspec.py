"""Realms d'authentification Proxmox (Datacenter → Permissions → Realms) : LDAP, Active Directory, OpenID Connect (lot #379).

Paramètres lus dans le schéma officiel de Proxmox 9 (`apidoc.js`, `/access/domains`). Liste blanche PAR TYPE : un champ d'un autre type est refusé (422), un champ inconnu est ignoré.
Secrets (mot de passe de liaison LDAP, clé OpenID) : `SecretStr`, jamais relus, renvoyés, journalisés ni mis dans une erreur ; Proxmox ne les relit pas non plus.
`pam` et `pve` sont intégrés : ni créés, ni supprimés, seuls `comment` et `default` se modifient.
Les chemins de certificats du nœud (`capath`, `cert`, `certkey`) ne sont volontairement pas exposés.
"""
import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, StrictBool, StrictInt, field_validator

from .metricsspec import check_host
from .networkspec import _t

REALM = re.compile(r"^[A-Za-z][A-Za-z0-9._\-]{1,31}$")
BUILTIN = ("pam", "pve")
TYPES = ("ldap", "ad", "openid")
MODES = ("ldap", "ldaps", "ldap+starttls")
SSL_VERSIONS = ("tlsv1_2", "tlsv1_3")                                      # Proxmox accepte aussi tlsv1 et tlsv1_1 : refusés par Kaji (obsolètes)
SYNC_SCOPES = ("users", "groups", "both")
VANISHED = ("acl", "properties", "entry")
PHRASE = "COUPURE POSSIBLE"
NO_CONTROL = re.compile(r"^[^\x00-\x1f\x7f]*$")
ATTR = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")
ATTR_LIST = re.compile(r"^[A-Za-z0-9._\-]{1,64}(\s*[,;]\s*[A-Za-z0-9._\-]{1,64}){0,19}$")
SYNC_ATTRS = re.compile(r"^\w+=[^,\x00-\x1f\x7f]+(,\s*\w+=[^,\x00-\x1f\x7f]+)*$")
SCOPES = re.compile(r"^[\x21\x23-\x5b\x5d-\x7e]+( [\x21\x23-\x5b\x5d-\x7e]+)*$")
CLAIM = re.compile(r"^[A-Za-z0-9._\-]{1,256}$")
ACR = re.compile(r'^[^\x00-\x1f\x7f <>#"]*$')

# Nom Kaji -> nom Proxmox
WIRE = {"server1": "server1", "server2": "server2", "port": "port", "mode": "mode", "base_dn": "base_dn", "bind_dn": "bind_dn", "password": "password", "user_attr": "user_attr",
        "user_classes": "user_classes", "filter": "filter", "group_dn": "group_dn", "group_filter": "group_filter", "group_classes": "group_classes", "group_name_attr": "group_name_attr",
        "sync_attributes": "sync_attributes", "domain": "domain", "verify": "verify", "sslversion": "sslversion", "case_sensitive": "case-sensitive", "check_connection": "check-connection",
        "comment": "comment", "default": "default", "sync_defaults_options": "sync-defaults-options", "issuer_url": "issuer-url", "client_id": "client-id", "client_key": "client-key",
        "username_claim": "username-claim", "scopes": "scopes", "prompt": "prompt", "acr_values": "acr-values", "autocreate": "autocreate", "groups_autocreate": "groups-autocreate",
        "groups_claim": "groups-claim", "groups_overwrite": "groups-overwrite", "query_userinfo": "query-userinfo"}
_LDAP_COMMON = ("server1", "server2", "port", "mode", "bind_dn", "password", "filter", "group_filter", "sync_attributes", "verify", "sslversion", "case_sensitive",
                "check_connection", "comment", "default", "sync_defaults_options")
ALLOWED = {
    "ldap": frozenset(_LDAP_COMMON + ("base_dn", "user_attr", "user_classes", "group_dn", "group_classes", "group_name_attr")),
    "ad": frozenset(_LDAP_COMMON + ("domain",)),
    "openid": frozenset(("issuer_url", "client_id", "client_key", "username_claim", "scopes", "prompt", "acr_values", "autocreate", "groups_autocreate", "groups_claim", "groups_overwrite",
                         "query_userinfo", "comment", "default")),
    "pam": frozenset(("comment", "default")), "pve": frozenset(("comment", "default")),
}
REQUIRED = {"ldap": ("server1", "base_dn", "user_attr"), "ad": ("server1", "domain"), "openid": ("issuer_url", "client_id")}
SECRETS = ("password", "client_key")
# Champs dont le changement peut empêcher les comptes du realm de se connecter : exigent la phrase quand le realm a des comptes.
LOGIN_FIELDS = frozenset(("server1", "server2", "port", "mode", "base_dn", "bind_dn", "password", "user_attr", "domain", "verify", "sslversion", "case_sensitive", "issuer_url",
                          "client_id", "client_key", "username_claim", "scopes", "prompt", "acr_values", "autocreate"))
CLEARABLE = ("server2", "port", "mode", "bind_dn", "password", "filter", "group_filter", "sync_attributes", "verify", "sslversion", "case_sensitive", "check_connection", "comment",
             "default", "sync_defaults_options", "user_classes", "group_dn", "group_classes", "group_name_attr", "client_key", "username_claim", "scopes", "prompt", "acr_values",
             "autocreate", "groups_autocreate", "groups_claim", "groups_overwrite", "query_userinfo")
PUBLIC_STR = ("server1", "server2", "mode", "base_dn", "bind_dn", "user_attr", "user_classes", "filter", "group_dn", "group_filter", "group_classes", "group_name_attr", "sync_attributes",
              "domain", "sslversion", "comment", "issuer_url", "client_id", "username_claim", "scopes", "prompt", "acr_values", "groups_claim")
PUBLIC_BOOL = ("verify", "case_sensitive", "check_connection", "default", "autocreate", "groups_autocreate", "groups_overwrite", "query_userinfo")


def check_issuer(v: str) -> str:
    m = re.fullmatch(r"https://(?P<h>[A-Za-z0-9.\-]{1,253})(:(?P<p>[0-9]{1,5}))?(?P<path>/[^\s?#@\x00-\x1f\x7f]*)?", v)
    if not m:
        raise ValueError("Adresse de l'émetteur invalide (https://hôte[:port][/chemin], sans identifiants ni paramètres)")
    if m.group("p") and not 1 <= int(m.group("p")) <= 65535:
        raise ValueError("Port invalide")
    check_host(m.group("h"))
    return v


class SyncDefaults(BaseModel):
    scope: Literal[SYNC_SCOPES] | None = None                                       # type: ignore[valid-type]
    enable_new: StrictBool | None = None
    remove_vanished: list[Literal[VANISHED]] | None = Field(default=None, max_length=3)  # type: ignore[valid-type]


def sync_string(d: SyncDefaults) -> str:
    parts = ([f"scope={d.scope}"] if d.scope else []) + ([f"enable-new={int(d.enable_new)}"] if d.enable_new is not None else [])
    if d.remove_vanished is not None:
        parts.append("remove-vanished=" + (";".join(dict.fromkeys(d.remove_vanished)) or "none"))
    return ",".join(parts)


class RealmFields(BaseModel):
    server1: str | None = Field(default=None, max_length=256)
    server2: str | None = Field(default=None, max_length=256)
    port: StrictInt | None = Field(default=None, ge=1, le=65535)
    mode: Literal[MODES] | None = None                                              # type: ignore[valid-type]
    base_dn: str | None = Field(default=None, max_length=256)
    bind_dn: str | None = Field(default=None, max_length=256)
    password: SecretStr | None = None
    user_attr: str | None = Field(default=None, max_length=256)
    user_classes: str | None = Field(default=None, max_length=256)
    filter: str | None = Field(default=None, max_length=2048)
    group_dn: str | None = Field(default=None, max_length=256)
    group_filter: str | None = Field(default=None, max_length=2048)
    group_classes: str | None = Field(default=None, max_length=256)
    group_name_attr: str | None = Field(default=None, max_length=64)
    sync_attributes: str | None = Field(default=None, max_length=512)
    domain: str | None = Field(default=None, max_length=256)
    verify: StrictBool | None = None
    sslversion: Literal[SSL_VERSIONS] | None = None                                 # type: ignore[valid-type]
    case_sensitive: StrictBool | None = None
    check_connection: StrictBool | None = None
    comment: str | None = Field(default=None, max_length=512)
    default: StrictBool | None = None
    sync_defaults_options: SyncDefaults | None = None
    issuer_url: str | None = Field(default=None, max_length=256)
    client_id: str | None = Field(default=None, max_length=256)
    client_key: SecretStr | None = None
    username_claim: str | None = Field(default=None, max_length=64)
    scopes: str | None = Field(default=None, max_length=256)
    prompt: str | None = Field(default=None, max_length=64)
    acr_values: str | None = Field(default=None, max_length=256)
    autocreate: StrictBool | None = None
    groups_autocreate: StrictBool | None = None
    groups_claim: str | None = Field(default=None, max_length=256)
    groups_overwrite: StrictBool | None = None
    query_userinfo: StrictBool | None = None

    @field_validator("server1", "server2")
    @classmethod
    def _host(cls, v):
        return check_host(v) if v is not None else v

    @field_validator("base_dn", "bind_dn", "group_dn", "filter", "group_filter", "comment", "domain", "client_id")
    @classmethod
    def _plain(cls, v):
        if v is not None and (not v.strip() or not NO_CONTROL.fullmatch(v)):
            raise ValueError("Valeur vide ou caractère de contrôle interdit")
        return v

    @field_validator("domain", "client_id")
    @classmethod
    def _nospace(cls, v):
        if v is not None and not re.fullmatch(r"\S+", v):
            raise ValueError("Pas d'espace dans cette valeur")
        return v

    @field_validator("user_attr")
    @classmethod
    def _uattr(cls, v):
        if v is not None and not re.fullmatch(r"[^\s\x00-\x1f\x7f]{2,256}", v):
            raise ValueError("Attribut invalide (2 caractères au moins, sans espace)")
        return v

    @field_validator("user_classes", "group_classes")
    @classmethod
    def _classes(cls, v):
        if v is not None and not ATTR_LIST.fullmatch(v):
            raise ValueError("Liste de classes d'objets invalide (noms séparés par des virgules)")
        return v

    @field_validator("group_name_attr")
    @classmethod
    def _gattr(cls, v):
        if v is not None and not ATTR.fullmatch(v):
            raise ValueError("Attribut invalide")
        return v

    @field_validator("sync_attributes")
    @classmethod
    def _sattr(cls, v):
        if v is not None and not SYNC_ATTRS.fullmatch(v):
            raise ValueError("Attributs de synchronisation invalides (cle=valeur séparés par des virgules)")
        return v

    @field_validator("password", "client_key")
    @classmethod
    def _secret(cls, v):
        if v is not None and (not v.get_secret_value() or len(v.get_secret_value()) > 512 or not NO_CONTROL.fullmatch(v.get_secret_value())):
            raise ValueError("Secret invalide (vide, trop long ou caractère de contrôle)")
        return v

    @field_validator("issuer_url")
    @classmethod
    def _issuer(cls, v):
        return check_issuer(v) if v is not None else v

    @field_validator("username_claim")
    @classmethod
    def _uclaim(cls, v):
        if v is not None and not ATTR.fullmatch(v):
            raise ValueError("Revendication invalide")
        return v

    @field_validator("groups_claim")
    @classmethod
    def _gclaim(cls, v):
        if v is not None and not CLAIM.fullmatch(v):
            raise ValueError("Revendication invalide")
        return v

    @field_validator("scopes")
    @classmethod
    def _scopes(cls, v):
        if v is not None and not SCOPES.fullmatch(v):
            raise ValueError("Portées invalides (mots séparés par un espace)")
        return v

    @field_validator("prompt")
    @classmethod
    def _prompt(cls, v):
        if v is not None and not re.fullmatch(r"\S{1,64}", v) or (v is not None and not NO_CONTROL.fullmatch(v)):
            raise ValueError("Valeur de prompt invalide")
        return v

    @field_validator("acr_values")
    @classmethod
    def _acr(cls, v):
        if v is not None and not ACR.fullmatch(v):
            raise ValueError("Valeurs ACR invalides")
        return v


class RealmCreate(RealmFields):
    realm: str = Field(max_length=32)
    type: Literal[TYPES]                                                            # type: ignore[valid-type]
    confirm: StrictBool = False
    type_name: str | None = Field(default=None, max_length=40, description="Identifiant du realm retapé")
    dry_run: StrictBool = False

    @field_validator("realm")
    @classmethod
    def _realm(cls, v):
        if not REALM.fullmatch(v):
            raise ValueError("Identifiant de realm invalide (lettre, puis lettres, chiffres, . _ -, 32 caractères au plus)")
        if v in BUILTIN:
            raise ValueError("Les realms pam et pve sont intégrés")
        return v


class RealmUpdate(RealmFields):
    clear: list[Literal[CLEARABLE]] = Field(default=[], max_length=len(CLEARABLE))  # type: ignore[valid-type]
    digest: str | None = Field(default=None, max_length=64)
    confirm: StrictBool = False
    acknowledge_cut_access: StrictBool = False
    type_name: str | None = Field(default=None, max_length=40, description="Identifiant du realm retapé")
    phrase: str | None = Field(default=None, max_length=40, description="« COUPURE POSSIBLE » quand des comptes du realm peuvent perdre leur connexion")
    dry_run: StrictBool = False


class RealmSync(BaseModel):
    scope: Literal[SYNC_SCOPES] | None = None                                       # type: ignore[valid-type]
    enable_new: StrictBool | None = None
    remove_vanished: list[Literal[VANISHED]] = Field(default=[], max_length=3)       # type: ignore[valid-type]
    dry_run: StrictBool = True                                                      # par défaut on simule : rien n'est écrit
    confirm: StrictBool = False
    acknowledge_cut_access: StrictBool = False
    type_name: str | None = Field(default=None, max_length=40, description="Identifiant du realm retapé")
    phrase: str | None = Field(default=None, max_length=40, description="« COUPURE POSSIBLE » quand la synchronisation peut supprimer des comptes ou des droits")


def _wire(v) -> str:
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, SecretStr):
        return v.get_secret_value()
    return str(v)


def build_params(typ: str, body: RealmFields, clear: list[str], creating: bool) -> tuple[dict, list[str]]:
    """`(paramètres Proxmox, réglages à retirer)`. Un champ d'un autre type, ou un champ obligatoire absent, lève `ValueError`."""
    allowed = ALLOWED[typ]
    p: dict = {}
    for k, wire in WIRE.items():
        v = getattr(body, k)
        if v is None:
            continue
        if k not in allowed:
            raise ValueError(f"Le champ « {k} » ne s'applique pas à un realm {typ}")
        p[wire] = sync_string(v) if k == "sync_defaults_options" else _wire(v)
    if p.get("sync-defaults-options") == "":
        raise ValueError("Options de synchronisation vides")
    bad = [k for k in clear if k not in allowed]
    if bad:
        raise ValueError(f"Le réglage « {bad[0]} » ne s'applique pas à un realm {typ}")
    delete = list(dict.fromkeys(WIRE[k] for k in clear))
    if set(delete) & set(p):
        raise ValueError("Réglage à la fois modifié et retiré")
    if creating:
        missing = [k for k in REQUIRED[typ] if WIRE[k] not in p]
        if missing:
            raise ValueError(f"Champ obligatoire manquant : {missing[0]}")
    elif not p and not delete:
        raise ValueError("Aucune modification demandée")
    return p, delete


def touched_login_fields(body: RealmFields, clear: list[str]) -> list[str]:
    return sorted(k for k in LOGIN_FIELDS if getattr(body, k) is not None or k in clear)


def shape_realm(raw, name: str, typ: str | None = None) -> dict | None:
    """Un realm lu : champs publics de SON type seulement ; ni mot de passe ni clé, jamais."""
    if not isinstance(raw, dict):
        return None
    t = raw.get("type") if raw.get("type") in (*TYPES, *BUILTIN) else typ
    if t not in (*TYPES, *BUILTIN):
        return None
    out: dict = {"realm": name, "type": t, "builtin": t in BUILTIN}
    for k in PUBLIC_STR:
        if k in ALLOWED[t]:
            wire = WIRE[k]
            out[k] = _t(raw.get(wire), 2048) if isinstance(raw.get(wire), str) else None
    for k in PUBLIC_BOOL:
        if k in ALLOWED[t]:
            v = raw.get(WIRE[k])
            out[k] = True if v in (1, True, "1", "true") else False if v in (0, False, "0", "false") else None
    if "port" in ALLOWED[t]:
        port = raw.get("port")
        out["port"] = port if isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535 else None
    if "sync_defaults_options" in ALLOWED[t]:
        out["sync_defaults_options"] = _t(raw.get("sync-defaults-options"), 200) if isinstance(raw.get("sync-defaults-options"), str) else None
    return out


def digest_of(shaped: dict) -> str:
    return hashlib.sha256(json.dumps({k: v for k, v in shaped.items() if k != "digest"}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:40]
