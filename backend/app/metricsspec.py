"""Serveurs de métriques Proxmox (Datacenter → Metric Server : InfluxDB, Graphite, OpenTelemetry) : validation en liste blanche PAR TYPE (lot #149).

Un champ valable pour un autre type est refusé (422), un champ inconnu ignoré, jamais transmis. Les SECRETS (`token` d'InfluxDB, `otel_headers` d'OpenTelemetry) sont des `SecretStr` :
jamais renvoyés (seulement « défini »), jamais journalisés, jamais dans une erreur. `server` : nom d'hôte ou adresse IP, adresses locales littérales refusées (le nœud ouvrirait la connexion).
"""
import hashlib
import ipaddress
import json
import re
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, StrictBool, StrictInt, field_validator

from .networkspec import _t

ID = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{1,63}$")
HOST = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9.\-]{0,251}[A-Za-z0-9])?|[0-9A-Fa-f:]{2,45})$")
LABEL = re.compile(r"^[A-Za-z0-9._\- @]{1,128}$")
GRAPHITE_PATH = re.compile(r"^[A-Za-z0-9_\-]{1,64}(?:\.[A-Za-z0-9_\-]{1,64}){0,15}$")
URL_PATH = re.compile(r"^/?[A-Za-z0-9._\-]{1,64}(?:/[A-Za-z0-9._\-]{1,64}){0,7}/?$|^/$")
TOKEN = re.compile(r"^[A-Za-z0-9._~+/=:\-]{1,512}$")
B64 = re.compile(r"^[A-Za-z0-9+/=]{1,1024}$")
TYPES = ("influxdb", "graphite", "opentelemetry")
# champ de l'API -> paramètre Proxmox
WIRE = {"server": "server", "port": "port", "disable": "disable",
        "influxdbproto": "influxdbproto", "organization": "organization", "bucket": "bucket", "token": "token", "max_body_size": "max-body-size", "mtu": "mtu",
        "verify_certificate": "verify-certificate", "api_path_prefix": "api-path-prefix",
        "proto": "proto", "path": "path", "timeout": "timeout",
        "otel_protocol": "otel-protocol", "otel_path": "otel-path", "otel_timeout": "otel-timeout", "otel_compression": "otel-compression", "otel_verify_ssl": "otel-verify-ssl",
        "otel_max_body_size": "otel-max-body-size", "otel_headers": "otel-headers", "otel_resource_attributes": "otel-resource-attributes"}
COMMON = ("server", "port", "disable")
BY_TYPE = {
    "influxdb": COMMON + ("influxdbproto", "organization", "bucket", "token", "max_body_size", "mtu", "verify_certificate", "api_path_prefix"),
    "graphite": COMMON + ("proto", "path", "mtu", "timeout"),
    "opentelemetry": COMMON + ("otel_protocol", "otel_path", "otel_timeout", "otel_compression", "otel_verify_ssl", "otel_max_body_size", "otel_headers", "otel_resource_attributes"),
}
SECRETS = ("token", "otel_headers")
BOOLS = ("disable", "verify_certificate", "otel_verify_ssl")
# réglages qu'on peut retirer (`delete=`), par type : tout sauf server, port, disable
CLEARABLE = {t: tuple(f for f in fields if f not in ("server", "port")) for t, fields in BY_TYPE.items()}
OUTBOUND = ("server", "port", "influxdbproto", "proto", "otel_protocol", "api_path_prefix", "otel_path")        # ce qui change où et comment les métriques sortent


def check_host(v: str) -> str:
    if not isinstance(v, str) or not HOST.fullmatch(v):
        raise ValueError("Nom d'hôte ou adresse IP invalide")
    h = v.lower().rstrip(".")
    if h == "localhost" or h.endswith(".localhost"):
        raise ValueError("Adresse locale refusée")
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        if ":" in h:
            raise ValueError("Adresse IP invalide") from None
        return v
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        raise ValueError("Adresse locale refusée")
    return v


def _label(v):
    if v is not None and not LABEL.fullmatch(v):
        raise ValueError("Caractères non autorisés")
    return v


class ServerFields(BaseModel):
    server: str | None = Field(default=None, max_length=253)
    port: StrictInt | None = Field(default=None, ge=1, le=65535)
    disable: StrictBool | None = None
    influxdbproto: Literal["udp", "http", "https"] | None = None
    organization: str | None = Field(default=None, max_length=128)
    bucket: str | None = Field(default=None, max_length=128)
    token: SecretStr | None = None
    max_body_size: StrictInt | None = Field(default=None, ge=1, le=1_000_000_000)
    mtu: StrictInt | None = Field(default=None, ge=512, le=65536)
    verify_certificate: StrictBool | None = None
    api_path_prefix: str | None = Field(default=None, max_length=600)
    proto: Literal["udp", "tcp"] | None = None
    path: str | None = Field(default=None, max_length=1100)
    timeout: StrictInt | None = Field(default=None, ge=0, le=300)
    otel_protocol: Literal["http", "https"] | None = None
    otel_path: str | None = Field(default=None, max_length=600)
    otel_timeout: StrictInt | None = Field(default=None, ge=1, le=10)
    otel_compression: Literal["none", "gzip"] | None = None
    otel_verify_ssl: StrictBool | None = None
    otel_max_body_size: StrictInt | None = Field(default=None, ge=1024, le=1_000_000_000)
    otel_headers: SecretStr | None = None
    otel_resource_attributes: str | None = Field(default=None, max_length=1024)
    confirm: StrictBool = False
    dry_run: StrictBool = False

    @field_validator("server")
    @classmethod
    def _server(cls, v):
        return check_host(v) if v is not None else v

    _l = field_validator("organization", "bucket")(lambda cls, v: _label(v))

    @field_validator("path")
    @classmethod
    def _gpath(cls, v):
        if v is not None and not GRAPHITE_PATH.fullmatch(v):
            raise ValueError("Chemin Graphite invalide (ex. proxmox.moncluster)")
        return v

    @field_validator("api_path_prefix", "otel_path")
    @classmethod
    def _upath(cls, v):
        if v is not None and (not URL_PATH.fullmatch(v) or ".." in v):
            raise ValueError("Chemin invalide")
        return v

    @field_validator("token")
    @classmethod
    def _token(cls, v):
        if v is not None and not TOKEN.fullmatch(v.get_secret_value()):
            raise ValueError("Jeton invalide")
        return v

    @field_validator("otel_headers")
    @classmethod
    def _hdr(cls, v):
        if v is not None and not B64.fullmatch(v.get_secret_value()):
            raise ValueError("En-têtes : JSON encodé en base64 attendu")
        return v

    @field_validator("otel_resource_attributes")
    @classmethod
    def _attrs(cls, v):
        if v is not None and not B64.fullmatch(v):
            raise ValueError("Attributs : JSON encodé en base64 attendu")
        return v


class ServerCreate(ServerFields):
    id: str = Field(pattern=ID.pattern)
    type: Literal["influxdb", "graphite", "opentelemetry"]


class ServerUpdate(ServerFields):
    clear: list[str] = Field(default=[], max_length=12)
    digest: str | None = Field(default=None, max_length=64)


def build(type_: str, body: ServerFields, clear: list[str], *, creating: bool) -> tuple[dict, list[str]]:
    """`(paramètres Proxmox, réglages à retirer : noms Proxmox)` ; un champ d'un autre type ou un retrait interdit lève `ValueError`."""
    allowed = BY_TYPE[type_]
    p: dict = {}
    for f in WIRE:
        v = getattr(body, f)
        if v is None:
            continue
        if f not in allowed:
            raise ValueError(f"Le champ « {f} » ne s'applique pas au type {type_}")
        v = v.get_secret_value() if isinstance(v, SecretStr) else v
        p[WIRE[f]] = (1 if v else 0) if f in BOOLS else v
    delete = list(dict.fromkeys(clear))
    bad = [c for c in delete if c not in CLEARABLE[type_]]
    if bad:
        raise ValueError("Réglage non retirable pour ce type")
    delete = [WIRE[c] for c in delete]                                                  # noms Proxmox (`max-body-size`), pas ceux de l'API (`max_body_size`)
    if set(delete) & set(p):
        raise ValueError("Réglage à la fois modifié et retiré")
    if creating and ("server" not in p or "port" not in p):
        raise ValueError("`server` et `port` sont obligatoires")
    if not creating and not p and not delete:
        raise ValueError("Aucune modification demandée")
    return p, delete


def shape_server(raw, type_hint: str | None = None) -> dict | None:
    """Un serveur de métriques en liste blanche. Les secrets ne sortent JAMAIS et ne sont pas relus par Proxmox : Kaji ne sait pas s'ils sont définis (constaté en réel)."""
    if not isinstance(raw, dict):
        return None
    sid = raw.get("id")
    typ = raw.get("type") if raw.get("type") in TYPES else type_hint
    if not isinstance(sid, str) or not ID.fullmatch(sid) or typ not in TYPES:
        return None

    def num(k):
        v = raw.get(k)
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    def flag(k):
        v = raw.get(k)
        return {1: True, "1": True, True: True, 0: False, "0": False, False: False}.get(v)

    def txt(k, n=128):
        return _t(raw.get(k), n)

    out = {"id": sid, "type": typ, "server": txt("server", 253), "port": num("port"), "disable": bool(flag("disable")), "digest": txt("digest", 64)}
    if typ == "influxdb":
        out.update({"influxdbproto": raw.get("influxdbproto") if raw.get("influxdbproto") in ("udp", "http", "https") else None, "organization": txt("organization"), "bucket": txt("bucket"),
                    "max_body_size": num("max-body-size"), "mtu": num("mtu"), "verify_certificate": flag("verify-certificate"), "api_path_prefix": txt("api-path-prefix", 600)})
    elif typ == "graphite":
        out.update({"proto": raw.get("proto") if raw.get("proto") in ("udp", "tcp") else None, "path": txt("path", 1100), "mtu": num("mtu"), "timeout": num("timeout")})
    else:
        out.update({"otel_protocol": raw.get("otel-protocol") if raw.get("otel-protocol") in ("http", "https") else None, "otel_path": txt("otel-path", 600), "otel_timeout": num("otel-timeout"),
                    "otel_compression": raw.get("otel-compression") if raw.get("otel-compression") in ("none", "gzip") else None, "otel_verify_ssl": flag("otel-verify-ssl"),
                    "otel_max_body_size": num("otel-max-body-size"), "otel_resource_attributes_set": bool(raw.get("otel-resource-attributes"))})
    return out


def digest_of(shaped: dict) -> str:
    """Empreinte des valeurs lues (propre à Kaji : la lecture d'un serveur n'a pas de `digest` chez Proxmox, constaté en réel)."""
    return hashlib.sha256(json.dumps({k: v for k, v in shaped.items() if k != "digest"}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:40]


def shape_list(raw) -> list[dict]:
    rows = [r for r in raw if isinstance(r, dict)][:200] if isinstance(raw, list) else []
    out = [{"id": s["id"], "type": s["type"], "server": s["server"], "port": s["port"], "disable": s["disable"]} for r in rows if (s := shape_server(r))]
    return sorted(out, key=lambda x: x["id"])
