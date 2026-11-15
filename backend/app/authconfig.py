"""Réglages du SSO (OIDC) et de l'annuaire (LDAP) saisis dans l'interface (lot #443). Détail : `docs/api/auth-settings.md`.

- Les réglages de la BASE priment sur ceux du `.env` ; sans ligne en base, le `.env` s'applique tel quel (aucun changement pour une installation existante).
- Les SECRETS (mot de passe du compte de lecture, secret du client SSO) sont chiffrés avec `KAJI_SECRET_KEY`, en écriture seule : ni l'API ni l'audit ne les renvoient ; on sait seulement s'ils sont définis.
- Chaque champ est validé (type, bornes, listes blanches) AVANT d'être gardé ; une configuration que le fournisseur concerné juge invalide n'est jamais enregistrée.
- Le mot de passe local (et donc l'accès d'un administrateur) ne dépend jamais de ces réglages : une erreur ici ne verrouille personne dehors.
"""
import json
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from . import ldaplogin, oidc
from .config import Settings, get_settings
from .crypto import decrypt, encrypt
from .models import AuthSetting

PROVIDERS = ("ldap", "oidc")
# nom du réglage → type ; les secrets sont listés à part
PLAIN = {
    "ldap": {"url": str, "start_tls": bool, "ca_file": str, "tls_server_name": str, "base_dn": str, "bind_dn": str, "user_filter": str, "username_attr": str, "timeout": int,
             "auto_create": bool, "default_role": str, "allow_admin": bool, "groups_attr": str, "admin_group": str, "operator_group": str, "label": str},
    "oidc": {"issuer": str, "client_id": str, "redirect_uri": str, "scopes": str, "username_claim": str, "auto_create": bool, "default_role": str, "allow_admin": bool, "groups_claim": str, "admin_group": str, "operator_group": str, "label": str},
}
SECRETS = {"ldap": ("bind_password",), "oidc": ("client_secret",)}
MAX_LEN = 512


class SettingError(ValueError):
    """Valeur refusée : le texte dit QUEL réglage, jamais la valeur."""


def _field(provider: str, name: str) -> str:
    return f"kaji_{provider}_{name}"


def check_provider(provider: str) -> str:
    if provider not in PROVIDERS:
        raise SettingError("fournisseur inconnu")
    return provider


def clean_value(provider: str, name: str, value):
    """Valeur validée et normalisée d'un réglage non secret, ou `SettingError`."""
    kind = PLAIN[provider].get(name)
    if kind is None:
        raise SettingError(f"réglage inconnu : {name}")
    if kind is bool:
        if not isinstance(value, bool):
            raise SettingError(f"{name} : vrai ou faux attendu")
        return value
    if kind is int:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 30:
            raise SettingError(f"{name} : entier de 1 à 30 attendu")
        return value
    if not isinstance(value, str) or len(value) > MAX_LEN or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise SettingError(f"{name} : texte de {MAX_LEN} caractères au plus, sans caractère de contrôle")
    value = value.strip()
    if name == "ca_file" and value and (not value.startswith("/") or ".." in value.split("/") or len(value) > 255):
        raise SettingError("ca_file : chemin absolu sans « .. » attendu")
    if name in ("default_role",) and value not in ("operator", "viewer"):
        raise SettingError("default_role : operator ou viewer (jamais admin)")
    if name == "tls_server_name" and value and not ldaplogin.TLS_NAME.fullmatch(value):
        raise SettingError("tls_server_name : nom DNS attendu (lettres, chiffres, points et tirets ; pas de joker)")
    if name == "url" and value and urlsplit(value).scheme not in ("ldap", "ldaps"):
        raise SettingError("url : ldaps:// (ou ldap:// avec STARTTLS) attendu")
    return value


def clean_secret(provider: str, name: str, value) -> str:
    if name not in SECRETS[provider]:
        raise SettingError(f"secret inconnu : {name}")
    if not isinstance(value, str) or not 1 <= len(value) <= 256 or "\x00" in value or "\n" in value or "\r" in value:
        raise SettingError(f"{name} : texte de 1 à 256 caractères, sur une seule ligne")
    return value


def _row(db: Session, provider: str) -> AuthSetting | None:
    return db.get(AuthSetting, provider)


def stored(db: Session, provider: str) -> tuple[dict, dict]:
    """`(réglages non secrets, secrets en clair)` gardés en base pour ce fournisseur (vides sans ligne). Les secrets ne servent qu'à construire la configuration effective."""
    row = _row(db, provider)
    if row is None:
        return {}, {}
    try:
        values = {k: v for k, v in json.loads(row.values_json or "{}").items() if k in PLAIN[provider]}
    except ValueError:
        values = {}
    secrets = {}
    if row.secret_enc:
        try:
            secrets = {k: v for k, v in json.loads(decrypt(get_settings().kaji_secret_key, row.secret_enc)).items() if k in SECRETS[provider] and isinstance(v, str)}
        except ValueError:
            secrets = {}                                              # clé changée : secrets illisibles = non définis (le texte de l'interface le dit)
    return values, secrets


def overlay(provider: str, values: dict, secrets: dict, base: Settings | None = None) -> Settings:
    base = base or get_settings()
    update = {_field(provider, k): v for k, v in values.items()}
    update.update({_field(provider, k): v for k, v in secrets.items()})
    return base.model_copy(update=update)


def effective(db: Session, provider: str) -> Settings:
    """Les réglages à appliquer : le `.env`, surchargé par la base."""
    values, secrets = stored(db, provider)
    return overlay(provider, values, secrets)


def preview(db: Session, provider: str, values: dict, secrets: dict) -> Settings:
    """La configuration qu'on obtiendrait en enregistrant `values` / `secrets` par-dessus l'existant, SANS rien écrire (test de connexion avant enregistrement). Lève `SettingError` si un champ est invalide."""
    check_provider(provider)
    new_values = {k: clean_value(provider, k, v) for k, v in values.items()}
    new_secrets = {k: clean_secret(provider, k, v) for k, v in secrets.items()}
    old_values, old_secrets = stored(db, provider)
    return overlay(provider, {**old_values, **new_values}, {**old_secrets, **new_secrets})


def problems(provider: str, s: Settings) -> list[str]:
    """Pourquoi cette configuration est inutilisable (liste vide : valide, ou fonction désactivée)."""
    if provider == "oidc":
        return oidc.check_config(s)
    if not ldaplogin.enabled(s):
        return []
    p = ldaplogin.configuration_problem(s)
    return [p] if p else []


def view(db: Session, provider: str) -> dict:
    """Ce que l'interface voit : valeurs EFFECTIVES non secrètes, quels secrets sont définis, d'où vient la configuration. Jamais un secret."""
    s = effective(db, provider)
    row = _row(db, provider)
    _values, secrets = stored(db, provider)
    on = oidc.enabled(s) if provider == "oidc" else ldaplogin.enabled(s)
    return {"provider": provider, "enabled": on, "source": "database" if row is not None else ("env" if on else "none"),
            "values": {k: getattr(s, _field(provider, k)) for k in PLAIN[provider]},
            "secrets": {k: bool(getattr(s, _field(provider, k)) or secrets.get(k)) for k in SECRETS[provider]},
            "problems": problems(provider, s), "updated_by": row.updated_by if row is not None else None}


def save(db: Session, provider: str, values: dict, secrets: dict, clear_secrets: list[str], user: str, *, commit: bool = True) -> list[str]:
    """Enregistre (fusionne avec ce qui existe) et renvoie la liste des NOMS modifiés. Lève `SettingError` si un champ est invalide ou si la configuration résultante est refusée par le fournisseur."""
    check_provider(provider)
    new_values = {k: clean_value(provider, k, v) for k, v in values.items()}
    new_secrets = {k: clean_secret(provider, k, v) for k, v in secrets.items()}
    for k in clear_secrets:
        if k not in SECRETS[provider]:
            raise SettingError(f"secret inconnu : {k}")
    if set(new_secrets) & set(clear_secrets):
        raise SettingError("un secret ne peut pas être défini et retiré à la fois")
    old_values, old_secrets = stored(db, provider)
    merged_values = {**old_values, **new_values}
    merged_secrets = {k: v for k, v in {**old_secrets, **new_secrets}.items() if k not in clear_secrets}
    if errs := problems(provider, overlay(provider, merged_values, merged_secrets)):
        raise SettingError("configuration refusée : " + " ; ".join(errs))
    changed = [k for k, v in new_values.items() if old_values.get(k) != v] + [f"{k} (secret défini)" for k in new_secrets] + [f"{k} (secret retiré)" for k in clear_secrets if k in old_secrets]
    if not commit:
        return changed
    row = _row(db, provider)
    if row is None:
        row = AuthSetting(provider=provider)
        db.add(row)
    row.values_json = json.dumps(merged_values, sort_keys=True)
    row.secret_enc = encrypt(get_settings().kaji_secret_key, json.dumps(merged_secrets)) if merged_secrets else None
    row.updated_by = user[:64]
    db.commit()
    if provider == "oidc":
        oidc.reset_cache()
    return changed


def remove(db: Session, provider: str) -> bool:
    row = _row(db, check_provider(provider))
    if row is None:
        return False
    db.delete(row)
    db.commit()
    if provider == "oidc":
        oidc.reset_cache()
    return True
