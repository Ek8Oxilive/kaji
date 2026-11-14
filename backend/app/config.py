from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    kaji_secret_key: str
    # Seulement pendant une rotation de KAJI_SECRET_KEY : l'ANCIENNE clé (`python -m app.admin_cli rotate-secret-key --yes`, docs/runbook.md). Ne sert à rien le reste du temps.
    kaji_secret_key_previous: str = ""
    database_url: str = "sqlite:///./kaji.db"
    # Cookie de session « Secure » : mettre false uniquement en HTTP non-localhost
    kaji_cookie_secure: bool = True
    kaji_session_hours: int = 12
    # Derrière un reverse proxy : prend l'IP ajoutée par le proxy (dernière valeur de X-Forwarded-For) pour le
    # limiteur de connexions. À n'activer QUE derrière un proxy de confiance : sinon l'en-tête est falsifiable.
    kaji_trust_proxy: bool = False
    # Jeton de première configuration (facultatif) : tant qu'aucun compte n'existe, `POST /api/auth/setup` l'exige. Sans lui, le premier qui atteint le port crée le compte admin.
    kaji_setup_token: str = ""
    # Les entrées d'audit plus anciennes sont supprimées (0 = conserver indéfiniment)
    kaji_audit_retention_days: int = 365
    # Identifiants de machines que Kaji refuse de supprimer, quoi qu'il arrive (ex. "105,108")
    kaji_protected_vmids: str = ""
    # Option (décision d'Enzo, 2026-11-13) : le token permanent de Kaji, à qui le propriétaire a donné les droits d'administration,
    # peut ouvrir la session administrateur d'un clic, sans coller de token. Désactivée par défaut : un Kaji compromis aurait alors ces droits.
    kaji_admin_use_kaji_token: bool = False
    # Planificateur d'actions (lot #411) : une seule instance de Kaji doit le faire tourner (un seul worker). `false` le coupe (tests, maintenance).
    kaji_scheduler: bool = True
    # Jetons Proxmox PERSONNELS (lot #440, option A du cadrage) : chaque utilisateur de Kaji enregistre son propre jeton, Proxmox applique ses droits et son journal le nomme.
    # La clé qui les chiffre est SÉPARÉE de `KAJI_SECRET_KEY` : `KAJI_TOKEN_KEY` (ou `KAJI_TOKEN_KEY_FILE`, un fichier hors de `.env` et hors de la sauvegarde de la base).
    # `KAJI_TOKEN_KEY_PREVIOUS` : l'ancienne clé, le temps d'une rotation (`python -m app.admin_cli rotate-token-key`).
    kaji_token_key: str = ""
    kaji_token_key_file: str = ""
    kaji_token_key_previous: str = ""
    # `true` : un utilisateur sans jeton personnel n'a PAS accès à Proxmox (au lieu de se rabattre sur le jeton partagé de la connexion).
    kaji_require_user_token: bool = False
    # Durée de vie maximale (jours) acceptée pour un jeton personnel : au-delà, l'enregistrement est refusé.
    kaji_user_token_max_days: int = 90

    @property
    def protected_vmids(self) -> set[int]:
        return {int(x) for x in self.kaji_protected_vmids.replace(" ", "").split(",") if x.isdigit()}


WEAK_SECRET_KEYS = ("", "changeme", "change-me", "secret", "password")
MIN_SECRET_KEY_LENGTH = 32


def check_secret_key(key: str) -> str | None:
    """`KAJI_SECRET_KEY` signe les sessions et chiffre les jetons Proxmox. Lève une erreur pour une valeur de démonstration (celle de `.env.example`) ;
    renvoie un avertissement (texte) pour une clé de moins de 32 caractères, sans bloquer un déploiement existant ; `None` si tout va bien."""
    if key.strip().lower() in WEAK_SECRET_KEYS:
        raise RuntimeError("KAJI_SECRET_KEY est vide ou vaut la valeur d'exemple : génère-en une avec python3 -c \"import secrets; print(secrets.token_urlsafe(48))\"")
    if len(key) < MIN_SECRET_KEY_LENGTH:
        return f"KAJI_SECRET_KEY est courte ({len(key)} caractères) : utilise au moins {MIN_SECRET_KEY_LENGTH} caractères aléatoires (le changer invalide les sessions ET les jetons enregistrés)"
    return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
