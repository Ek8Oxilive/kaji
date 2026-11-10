"""Notifications Proxmox en ÉCRITURE (cibles de 4 types, règles) : validation en liste blanche PAR TYPE (lot #151, étape 2).

Secrets (`password` SMTP, `token` Gotify, valeurs des en-têtes et des secrets d'un webhook) : `SecretStr`, jamais renvoyés, journalisés ni dans une erreur ; Proxmox ne les relit pas.
Les valeurs d'en-têtes et de secrets d'un webhook, et son corps, sont saisis EN CLAIR et encodés en base64 par Kaji (c'est ce que Proxmox attend). `url` / `server` : adresses locales refusées.
Les commentaires sont en ASCII imprimable : Proxmox altère les accents dans les commentaires de la HA (constaté en réel) et rien ne prouve que ce soit différent ici.
"""
import base64
import re
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, StrictBool, StrictInt, field_validator

from .isospec import check_url
from .metricsspec import check_host
from .notificationspec import FIELD, HEADER_NAME, NAME, SEVERITIES

EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,190}$")
USERID = re.compile(r"^[A-Za-z0-9._\-]{1,64}@[A-Za-z0-9\-]{1,32}$")
ASCII_TEXT = re.compile(r"^[\x20-\x7e]*$")
AUTHOR = re.compile(r"^[A-Za-z0-9 ._\-]{1,120}$")
CALENDAR = re.compile(r"^[A-Za-z0-9*/,:\-. ]{1,128}$")
MATCH_FIELD = re.compile(r"^(exact|regex):[A-Za-z0-9_\-]{1,64}=[\x20-\x7e]{1,200}$")
NO_CONTROL = re.compile(r"^[^\x00-\x1f\x7f]*$")
TYPES = ("sendmail", "smtp", "gotify", "webhook")
WIRE = {"author": "author", "comment": "comment", "disable": "disable", "from_address": "from-address", "mailto": "mailto", "mailto_user": "mailto-user", "mode": "mode", "port": "port",
        "server": "server", "username": "username", "password": "password", "token": "token", "url": "url", "method": "method", "headers": "header", "secrets": "secret", "body": "body"}
BY_TYPE = {
    "sendmail": ("author", "comment", "disable", "from_address", "mailto", "mailto_user"),
    "smtp": ("author", "comment", "disable", "from_address", "mailto", "mailto_user", "mode", "port", "server", "username", "password"),
    "gotify": ("comment", "disable", "server", "token"),
    "webhook": ("comment", "disable", "url", "method", "headers", "secrets", "body"),
}
REQUIRED = {"sendmail": (), "smtp": ("from_address", "server"), "gotify": ("server", "token"), "webhook": ("url", "method")}
SECRET_FIELDS = ("password", "token", "headers", "secrets")
BOOLS = ("disable",)
# ce qui change OÙ ou COMMENT partent les messages
OUTBOUND = ("server", "port", "mode", "url", "method", "mailto", "mailto_user", "from_address", "username")


def _ascii(v):
    if v is not None and not ASCII_TEXT.fullmatch(v):
        raise ValueError("Caractères ASCII imprimables seulement (Proxmox altère les accents des commentaires)")
    return v


class Pair(BaseModel):
    """En-tête ou secret d'un webhook : `name` + `value` EN CLAIR (encodée en base64 pour Proxmox). La valeur est un secret."""
    name: str = Field(max_length=64)
    value: SecretStr = Field(max_length=1024)

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        if not HEADER_NAME.fullmatch(v):
            raise ValueError("Nom invalide")
        return v

    @field_validator("value")
    @classmethod
    def _v(cls, v):
        s = v.get_secret_value()
        if not s or not NO_CONTROL.fullmatch(s):
            raise ValueError("Valeur invalide")
        return v


class Locks(BaseModel):
    confirm: StrictBool = False
    dry_run: StrictBool = False


class EndpointFields(Locks):
    author: str | None = Field(default=None, max_length=120)
    comment: str | None = Field(default=None, max_length=500)
    disable: StrictBool | None = None
    from_address: str | None = Field(default=None, max_length=254)
    mailto: list[str] | None = Field(default=None, max_length=20)
    mailto_user: list[str] | None = Field(default=None, max_length=20)
    mode: Literal["insecure", "starttls", "tls"] | None = None
    port: StrictInt | None = Field(default=None, ge=1, le=65535)
    server: str | None = Field(default=None, max_length=300)
    username: str | None = Field(default=None, max_length=128)
    password: SecretStr | None = Field(default=None, max_length=256)
    token: SecretStr | None = Field(default=None, max_length=512)
    url: str | None = Field(default=None, max_length=500)
    method: Literal["post", "put", "get"] | None = None
    headers: list[Pair] | None = Field(default=None, max_length=20)
    secrets: list[Pair] | None = Field(default=None, max_length=20)
    body: str | None = Field(default=None, max_length=4096, description="Modèle du corps, en clair (encodé en base64 par Kaji)")

    _c = field_validator("comment")(lambda cls, v: _ascii(v))

    @field_validator("author")
    @classmethod
    def _author(cls, v):
        if v is not None and not AUTHOR.fullmatch(v):
            raise ValueError("Auteur invalide")
        return v

    @field_validator("from_address")
    @classmethod
    def _from(cls, v):
        if v is not None and not EMAIL.fullmatch(v):
            raise ValueError("Adresse d'expédition invalide")
        return v

    @field_validator("mailto")
    @classmethod
    def _mailto(cls, v):
        if v is not None and (any(not EMAIL.fullmatch(x) for x in v) or len(set(v)) != len(v)):
            raise ValueError("Destinataires invalides ou en double")
        return v

    @field_validator("mailto_user")
    @classmethod
    def _users(cls, v):
        if v is not None and (any(not USERID.fullmatch(x) for x in v) or len(set(v)) != len(v)):
            raise ValueError("Utilisateurs invalides ou en double")
        return v

    @field_validator("username")
    @classmethod
    def _username(cls, v):
        if v is not None and (not v or not NO_CONTROL.fullmatch(v)):
            raise ValueError("Nom d'utilisateur invalide")
        return v

    @field_validator("password")
    @classmethod
    def _pw(cls, v):
        if v is not None and (not v.get_secret_value() or not NO_CONTROL.fullmatch(v.get_secret_value())):
            raise ValueError("Mot de passe invalide")
        return v

    @field_validator("token")
    @classmethod
    def _tok(cls, v):
        if v is not None and not re.fullmatch(r"^[A-Za-z0-9._~+/=:\-]{1,512}$", v.get_secret_value()):
            raise ValueError("Jeton invalide")
        return v

    @field_validator("body")
    @classmethod
    def _body(cls, v):
        if v is not None and not re.fullmatch(r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$", v):
            raise ValueError("Caractère de contrôle interdit")
        return v

    @field_validator("headers", "secrets")
    @classmethod
    def _pairs(cls, v):
        if v is not None and len({p.name.lower() for p in v}) != len(v):
            raise ValueError("Nom en double")
        return v


class EndpointCreate(EndpointFields):
    name: str = Field(pattern=NAME.pattern)


class EndpointUpdate(EndpointFields):
    clear: list[str] = Field(default=[], max_length=10)
    digest: str | None = Field(default=None, max_length=64)


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def check_endpoint_urls(typ: str, body: EndpointFields) -> None:
    if body.server is not None:
        if typ == "gotify":
            check_url(body.server)
        else:
            check_host(body.server)
    if body.url is not None:
        check_url(body.url)


def build_endpoint(typ: str, body: EndpointFields, clear: list[str], *, creating: bool) -> tuple[dict, list[str]]:
    """`(paramètres Proxmox, réglages à retirer)`. Un champ d'un autre type, un retrait interdit, un champ obligatoire absent : `ValueError`."""
    allowed = BY_TYPE[typ]
    try:
        check_endpoint_urls(typ, body)
    except ValueError as e:
        raise ValueError(str(e)) from None
    p: dict = {}
    for f, wire in WIRE.items():
        v = getattr(body, f)
        if v is None:
            continue
        if f not in allowed:
            raise ValueError(f"Le champ « {f} » ne s'applique pas au type {typ}")
        if f in ("headers", "secrets"):
            p[wire] = [f"{x.name}={_b64(x.value.get_secret_value())}" for x in v]
        elif f == "body":
            p[wire] = _b64(v)
        elif isinstance(v, SecretStr):
            p[wire] = v.get_secret_value()
        elif f in BOOLS:
            p[wire] = 1 if v else 0
        else:
            p[wire] = v
    delete = list(dict.fromkeys(clear))
    clearable = [f for f in allowed if f not in REQUIRED[typ] and f != "disable"] + ["disable"]
    if any(c not in clearable for c in delete):
        raise ValueError("Réglage non retirable pour ce type")
    delete_wire = [WIRE[c] for c in delete]
    if set(delete_wire) & set(p):
        raise ValueError("Réglage à la fois modifié et retiré")
    if creating and any(WIRE[r] not in p for r in REQUIRED[typ]):
        raise ValueError("Champs obligatoires : " + ", ".join(REQUIRED[typ]))
    if not creating and not p and not delete_wire:
        raise ValueError("Aucune modification demandée")
    return p, delete_wire


# ---------------------------------------------------------------- règles (matchers)
class MatcherFields(Locks):
    comment: str | None = Field(default=None, max_length=500)
    disable: StrictBool | None = None
    invert_match: StrictBool | None = None
    mode: Literal["all", "any"] | None = None
    match_field: list[str] | None = Field(default=None, max_length=20)
    match_severity: list[Literal["info", "notice", "warning", "error", "unknown"]] | None = Field(default=None, max_length=5)
    match_calendar: list[str] | None = Field(default=None, max_length=10)
    target: list[str] | None = Field(default=None, max_length=20)

    _c = field_validator("comment")(lambda cls, v: _ascii(v))

    @field_validator("match_field")
    @classmethod
    def _mf(cls, v):
        if v is not None and (any(not MATCH_FIELD.fullmatch(x) or not FIELD.fullmatch(x.split(":", 1)[1].split("=", 1)[0]) for x in v) or len(set(v)) != len(v)):
            raise ValueError("Champ de règle invalide (attendu exact:champ=valeur ou regex:champ=valeur)")
        return v

    @field_validator("match_calendar")
    @classmethod
    def _cal(cls, v):
        if v is not None and any(not CALENDAR.fullmatch(x) or not x.strip() for x in v):
            raise ValueError("Calendrier invalide")
        return v

    @field_validator("match_severity")
    @classmethod
    def _sev(cls, v):
        if v is not None and len(set(v)) != len(v):
            raise ValueError("Gravité en double")
        return v

    @field_validator("target")
    @classmethod
    def _tg(cls, v):
        if v is not None and (any(not NAME.fullmatch(x) for x in v) or len(set(v)) != len(v)):
            raise ValueError("Cible invalide ou en double")
        return v


class MatcherCreate(MatcherFields):
    name: str = Field(pattern=NAME.pattern)


class MatcherUpdate(MatcherFields):
    clear: list[Literal["comment", "disable", "invert_match", "mode", "match_field", "match_severity", "match_calendar", "target"]] = Field(default=[], max_length=8)
    digest: str | None = Field(default=None, max_length=64)


MATCHER_WIRE = {"comment": "comment", "disable": "disable", "invert_match": "invert-match", "mode": "mode", "match_field": "match-field", "match_severity": "match-severity",
                "match_calendar": "match-calendar", "target": "target"}


def build_matcher(body: MatcherFields, clear: list[str], *, creating: bool) -> tuple[dict, list[str]]:
    p: dict = {}
    for f, wire in MATCHER_WIRE.items():
        v = getattr(body, f)
        if v is None:
            continue
        p[wire] = (1 if v else 0) if isinstance(v, bool) else v
    delete = [MATCHER_WIRE[c] for c in dict.fromkeys(clear)]
    if set(delete) & set(p):
        raise ValueError("Réglage à la fois modifié et retiré")
    if creating and not p.get("target"):
        raise ValueError("Une règle doit viser au moins une cible")
    if not creating and not p and not delete:
        raise ValueError("Aucune modification demandée")
    if not creating and "target" in delete:
        raise ValueError("Une règle sans cible n'envoie rien : supprime-la ou désactive-la")
    return p, delete
