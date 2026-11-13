"""Migration distante d'une VM ou d'un conteneur vers un AUTRE cluster Proxmox (`remote_migrate`, « EXPERIMENTAL » chez Proxmox) : validation et construction (lot #390).

Schéma lu sur `apidoc.js` de Proxmox 9 : `POST /nodes/{node}/{qemu|lxc}/{vmid}/remote_migrate`, `target-endpoint` = `apitoken=PVEAPIToken=user@realm!token=SECRET,host=…[,fingerprint=…][,port=…]`.
Garde-fous : le jeton du cluster distant est un `SecretStr` (jamais renvoyé, journalisé ni mis dans une erreur) ; l'EMPREINTE du certificat distant est OBLIGATOIRE (Proxmox la laisse facultative :
Kaji ne se connecte jamais sans la vérifier) ; adresses locales refusées ; correspondances de stockages et de ponts validées une à une ; `delete` (supprime l'ORIGINAL après réussite) est verrouillé.
"""
import re

from pydantic import BaseModel, Field, SecretStr, StrictBool, StrictInt, field_validator

from .hardware import BRIDGE
from .metricsspec import check_host
from .vmspec import STORAGE

TOKEN_ID = re.compile(r"^[A-Za-z0-9._\-]{1,64}@[A-Za-z][A-Za-z0-9._\-]{1,31}![A-Za-z][A-Za-z0-9._\-]{1,63}$")
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
FINGERPRINT = re.compile(r"^([0-9A-Fa-f]{2}:){31}[0-9A-Fa-f]{2}$")
PHRASE = "COUPURE POSSIBLE"
MAX_PAIRS = 20


def check_pairs(v: str, ident: re.Pattern, what: str) -> str:
    """`1` (chaque source vers elle-même), un identifiant seul (tout vers lui) ou `source:cible,source:cible`."""
    if v == "1":
        return v
    items = v.split(",")
    if not 1 <= len(items) <= MAX_PAIRS:
        raise ValueError(f"Correspondance de {what} invalide")
    for it in items:
        parts = it.split(":")
        if len(parts) == 1 and len(items) == 1 and ident.fullmatch(parts[0]):
            continue
        if len(parts) == 2 and ident.fullmatch(parts[0]) and ident.fullmatch(parts[1]):
            continue
        raise ValueError(f"Correspondance de {what} invalide (un identifiant, ou source:cible séparés par des virgules)")
    return v


class RemoteMigrate(BaseModel):
    target_host: str = Field(max_length=253, description="Nom ou adresse IP d'un nœud du cluster distant")
    target_port: StrictInt | None = Field(default=None, ge=1, le=65535)
    target_token_id: str = Field(max_length=140, description="Jeton d'API du cluster distant : utilisateur@realm!nom")
    target_secret: SecretStr = Field(description="Secret du jeton distant : écriture seule")
    target_fingerprint: str = Field(max_length=95, description="Empreinte SHA-256 du certificat distant (obligatoire)")
    target_storage: str = Field(max_length=700)
    target_bridge: str = Field(max_length=400)
    target_vmid: StrictInt | None = Field(default=None, ge=100, le=999_999_999)
    online: StrictBool = False
    restart: StrictBool = False
    timeout: StrictInt | None = Field(default=None, ge=1, le=3600)
    bwlimit: StrictInt | None = Field(default=None, ge=0, le=1_000_000_000)
    delete: StrictBool = False
    confirm: StrictBool = False
    type_name: str | None = Field(default=None, max_length=80, description="Nom exact de la machine retapé (exigé avec delete)")
    acknowledge_cut_access: StrictBool = False
    phrase: str | None = Field(default=None, max_length=40, description="« COUPURE POSSIBLE » avec delete")
    dry_run: StrictBool = False

    @field_validator("target_host")
    @classmethod
    def _host(cls, v):
        return check_host(v)

    @field_validator("target_token_id")
    @classmethod
    def _token(cls, v):
        if not TOKEN_ID.fullmatch(v):
            raise ValueError("Jeton invalide (attendu : utilisateur@realm!nom)")
        return v

    @field_validator("target_secret")
    @classmethod
    def _secret(cls, v):
        if not UUID.fullmatch(v.get_secret_value()):
            raise ValueError("Secret de jeton invalide (UUID attendu)")
        return v

    @field_validator("target_fingerprint")
    @classmethod
    def _fp(cls, v):
        if not FINGERPRINT.fullmatch(v):
            raise ValueError("Empreinte invalide (SHA-256 : 32 octets hexadécimaux séparés par « : »)")
        return v.upper()

    @field_validator("target_storage")
    @classmethod
    def _storage(cls, v):
        return check_pairs(v, STORAGE, "stockages")

    @field_validator("target_bridge")
    @classmethod
    def _bridge(cls, v):
        return check_pairs(v, BRIDGE, "ponts")


def build_params(body: RemoteMigrate, gtype: str) -> dict:
    """Paramètres envoyés à Proxmox. `restart` et `timeout` ne concernent que les conteneurs."""
    if gtype != "lxc" and (body.restart or body.timeout is not None):
        raise ValueError("« restart » et « timeout » ne concernent que les conteneurs")
    endpoint = f"apitoken=PVEAPIToken={body.target_token_id}={body.target_secret.get_secret_value()},host={body.target_host}"
    endpoint += f",fingerprint={body.target_fingerprint}" + (f",port={body.target_port}" if body.target_port is not None else "")
    p: dict = {"target-endpoint": endpoint, "target-storage": body.target_storage, "target-bridge": body.target_bridge}
    if body.target_vmid is not None:
        p["target-vmid"] = body.target_vmid
    for k, v in (("online", body.online), ("restart", body.restart), ("delete", body.delete)):
        if v:
            p[k] = 1
    if body.timeout is not None:
        p["timeout"] = body.timeout
    if body.bwlimit is not None:
        p["bwlimit"] = body.bwlimit
    return p


def masked(params: dict) -> dict:
    return {k: ("défini (jeton masqué)" if k == "target-endpoint" else v) for k, v in params.items()}


def clean_error(msg: str, body: RemoteMigrate) -> str:
    """Message d'erreur de Proxmox sans le jeton ni la chaîne de connexion (Proxmox peut recopier le paramètre fautif)."""
    secret = body.target_secret.get_secret_value()
    out = msg.replace(secret, "…")
    return "Proxmox a refusé la migration (détail masqué : il pouvait contenir le jeton du cluster distant)" if "apitoken" in out.lower() or "PVEAPIToken" in out else out
