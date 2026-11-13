"""Double authentification (TFA) des utilisateurs Proxmox (Datacenter → Permissions → Two Factor) : lecture tolérante, écriture en liste blanche (lot #384).

Schéma lu sur `apidoc.js` de Proxmox 9 (`/access/tfa`). Gérés : lister les entrées, ajouter un TOTP ou des codes de secours (`recovery`), activer / désactiver, changer la description, supprimer.
Hors périmètre : enregistrer une clé WebAuthn ou U2F (cérémonie du navigateur), YubiKey OTP, et le `password` de l'utilisateur (Kaji n'en demande ni n'en transmet jamais).
Secrets : l'URI TOTP et le code de vérification sont des `SecretStr` ; le secret TOTP généré par Kaji n'est JAMAIS gardé côté serveur ; les codes de secours renvoyés par Proxmox ne sortent qu'une fois.
"""
import base64
import re
import secrets
from urllib.parse import quote

from pydantic import BaseModel, Field, SecretStr, StrictBool, field_validator

from .networkspec import _b, _int, _rows, _t

USERID = re.compile(r"^[A-Za-z0-9._\-]{1,64}@[A-Za-z][A-Za-z0-9._\-]{1,31}$")
ENTRY_ID = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")
TYPES = ("totp", "u2f", "webauthn", "recovery", "yubico")
ADD_TYPES = ("totp", "recovery")
DESC = re.compile(r"^[^\x00-\x1f\x7f]{0,255}$")
CODE = re.compile(r"^[0-9]{6,8}$")
TOTP_URI = re.compile(r"^otpauth://totp/(?P<label>[^?\s/]{1,200})\?(?P<query>[^\s#]{1,400})$")
SECRET32 = re.compile(r"^[A-Z2-7]{16,128}$")
ISSUER = "Kaji"
PHRASE = "COUPURE POSSIBLE"
MAX_USERS = 500
MAX_ENTRIES = 50


def check_userid(v: str) -> str:
    if not isinstance(v, str) or not USERID.fullmatch(v):
        raise ValueError("Identifiant invalide (attendu : nom@realm)")
    return v


def check_totp_uri(v: str) -> str:
    """URI `otpauth://totp/…` à secret base32, 6 à 8 chiffres, période de 30 s, SHA1 : le format que Proxmox accepte et que les applications d'authentification comprennent."""
    m = TOTP_URI.fullmatch(v)
    if not m:
        raise ValueError("URI TOTP invalide")
    params: dict[str, str] = {}
    for part in m.group("query").split("&"):
        k, sep, val = part.partition("=")
        if not sep or k in params or k not in ("secret", "issuer", "algorithm", "digits", "period"):
            raise ValueError("URI TOTP invalide (paramètre inconnu, double ou vide)")
        params[k] = val
    if "secret" not in params or not SECRET32.fullmatch(params["secret"]):
        raise ValueError("URI TOTP invalide (secret base32 de 16 caractères au moins attendu)")
    if params.get("algorithm", "SHA1") != "SHA1" or params.get("digits", "6") not in ("6", "7", "8") or params.get("period", "30") != "30":
        raise ValueError("URI TOTP non gérée (SHA1, 6 à 8 chiffres, période de 30 secondes seulement)")
    if not re.fullmatch(r"[A-Za-z0-9%._~\-]{0,200}", params.get("issuer", "")):
        raise ValueError("Émetteur invalide")
    return v


def new_totp(userid: str) -> dict:
    """Secret et URI TOTP neufs (20 octets aléatoires). Calculés à la demande, jamais gardés par Kaji : l'URI revient avec la requête d'ajout."""
    secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
    return {"secret": secret, "uri": f"otpauth://totp/{quote(ISSUER + ':' + userid, safe='')}?secret={secret}&issuer={quote(ISSUER, safe='')}&algorithm=SHA1&digits=6&period=30"}


def shape_entry(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    i, t = raw.get("id"), raw.get("type")
    if not isinstance(i, str) or not ENTRY_ID.fullmatch(i) or t not in TYPES:
        return None
    en = _b(raw.get("enable"))
    return {"id": i, "type": t, "description": _t(raw.get("description"), 255), "created": _int(raw.get("created")), "enabled": True if en is None else en}


def shape_entries(raw) -> list[dict]:
    return [e for r in (raw if isinstance(raw, list) else [])[:MAX_ENTRIES] if (e := shape_entry(r))]


def shape_tfa(raw) -> list[dict]:
    """`GET /access/tfa` : une ligne par utilisateur qui a des entrées. Aucun secret : Proxmox n'en renvoie pas."""
    out = []
    for r in _rows(raw)[:MAX_USERS]:
        uid = r.get("userid")
        if not isinstance(uid, str) or not USERID.fullmatch(uid):
            continue
        out.append({"userid": uid, "entries": shape_entries(r.get("entries")), "locked": bool(r.get("totp-locked")) or r.get("tfa-locked-until") not in (None, 0, False)})
    return sorted(out, key=lambda x: x["userid"])


def enabled_count(entries: list[dict]) -> int:
    return sum(1 for e in entries if e["enabled"])


class Confirmed(BaseModel):
    confirm: StrictBool = False
    type_name: str | None = Field(default=None, max_length=80, description="Identifiant de l'utilisateur retapé")
    acknowledge_cut_access: StrictBool = False
    phrase: str | None = Field(default=None, max_length=40, description="« COUPURE POSSIBLE » quand la double authentification s'active sur le compte")
    dry_run: StrictBool = False


class TotpSetup(BaseModel):
    userid: str = Field(max_length=80)

    _u = field_validator("userid")(lambda cls, v: check_userid(v))


class TfaAdd(Confirmed):
    userid: str = Field(max_length=80)
    type: str
    description: str | None = Field(default=None, max_length=255)
    totp: SecretStr | None = Field(default=None, max_length=700, description="URI TOTP (secret) : jamais renvoyée ni journalisée")
    value: SecretStr | None = Field(default=None, max_length=8, description="Code affiché par l'application d'authentification")

    _u = field_validator("userid")(lambda cls, v: check_userid(v))

    @field_validator("type")
    @classmethod
    def _type(cls, v):
        if v not in ADD_TYPES:
            raise ValueError("Type non géré (totp ou recovery ; WebAuthn et U2F demandent le navigateur)")
        return v

    @field_validator("description")
    @classmethod
    def _desc(cls, v):
        if v is not None and not DESC.fullmatch(v):
            raise ValueError("Description invalide (255 caractères au plus, sans caractère de contrôle)")
        return v

    @field_validator("totp")
    @classmethod
    def _totp(cls, v):
        if v is not None:
            check_totp_uri(v.get_secret_value())
        return v

    @field_validator("value")
    @classmethod
    def _value(cls, v):
        if v is not None and not CODE.fullmatch(v.get_secret_value()):
            raise ValueError("Code invalide (6 à 8 chiffres)")
        return v


class TfaUpdate(Confirmed):
    description: str | None = Field(default=None, max_length=255)
    enable: StrictBool | None = None

    @field_validator("description")
    @classmethod
    def _desc(cls, v):
        if v is not None and not DESC.fullmatch(v):
            raise ValueError("Description invalide (255 caractères au plus, sans caractère de contrôle)")
        return v


def add_params(body: TfaAdd) -> dict:
    """Paramètres envoyés à Proxmox. TOTP : l'URI ET le code de vérification sont exigés ; codes de secours : ni l'un ni l'autre."""
    p: dict = {"type": body.type}
    if body.description:
        p["description"] = body.description
    if body.type == "totp":
        if body.totp is None or body.value is None:
            raise ValueError("Un TOTP exige l'URI générée par Kaji et le code affiché par l'application")
        p["totp"] = body.totp.get_secret_value()
        p["value"] = body.value.get_secret_value()
    elif body.totp is not None or body.value is not None:
        raise ValueError("Des codes de secours n'acceptent ni URI ni code")
    return p


def update_params(body: TfaUpdate) -> dict:
    p: dict = {}
    if body.description is not None:
        p["description"] = body.description
    if body.enable is not None:
        p["enable"] = "1" if body.enable else "0"
    if not p:
        raise ValueError("Aucune modification demandée")
    return p
