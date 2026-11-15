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
    # Export de l'audit (lot #445), désactivé par défaut. `KAJI_AUDIT_FILE` : chemin ABSOLU d'un fichier JSON (une ligne par événement, droits 600, rotation par taille).
    # `KAJI_AUDIT_SYSLOG` : `udp://hôte:port` ou `tcp://hôte:port` (RFC 5424, facility local0). Les deux peuvent être actifs ; la base reste la source (conservation ci-dessus).
    kaji_audit_file: str = ""
    kaji_audit_file_max_mb: int = 10
    kaji_audit_file_backups: int = 10
    kaji_audit_syslog: str = ""
    # SSO (OIDC, lot #443) : désactivé tant que `KAJI_OIDC_ISSUER` est vide. Authorization Code + PKCE ; le mot de passe local reste le repli. `KAJI_OIDC_REDIRECT_URI` : l'adresse EXACTE de retour
    # (`https://<kaji>/api/auth/oidc/callback`), déclarée à l'identique chez le fournisseur. Un compte Kaji existant est relié à l'identité du fournisseur (par `KAJI_OIDC_USERNAME_CLAIM`) ;
    # `KAJI_OIDC_AUTO_CREATE=true` crée à la première connexion un compte de rôle `KAJI_OIDC_DEFAULT_ROLE` (jamais administrateur).
    kaji_oidc_issuer: str = ""
    kaji_oidc_client_id: str = ""
    kaji_oidc_client_secret: str = ""
    kaji_oidc_redirect_uri: str = ""
    kaji_oidc_scopes: str = "openid profile"
    kaji_oidc_username_claim: str = "preferred_username"
    kaji_oidc_auto_create: bool = False
    kaji_oidc_default_role: str = "viewer"
    kaji_oidc_groups_claim: str = "groups"          # champ de l'ID token qui liste les groupes (ajouter le périmètre `groups` chez le fournisseur)
    kaji_oidc_admin_group: str = ""                 # groupe dont les membres sont administrateurs de Kaji (vide : aucune correspondance, rôles inchangés) ; correspondance exacte
    kaji_oidc_operator_group: str = ""              # groupe dont les membres sont opérateurs
    kaji_oidc_allow_admin: bool = True           # un compte administrateur peut se connecter par le SSO (il doit déjà exister : jamais créé automatiquement) ; `false` les réserve au mot de passe local
    kaji_oidc_label: str = "SSO"
    # Connexion par annuaire LDAP / Active Directory (lot #443) : désactivée tant que `KAJI_LDAP_URL` est vide. Chiffrement OBLIGATOIRE (`ldaps://` ou `KAJI_LDAP_START_TLS=true`), certificat vérifié
    # (`KAJI_LDAP_CA_FILE` pour une autorité privée). Kaji cherche la personne avec le compte de lecture (`BIND_DN`), puis vérifie son mot de passe par une liaison à SON nom : il ne le garde jamais.
    # `USER_FILTER` contient `{username}` (ex. AD : `(sAMAccountName={username})`). Seuls les comptes opérateur et lecture seule se relient ; un administrateur garde son mot de passe local.
    kaji_ldap_url: str = ""
    kaji_ldap_start_tls: bool = False
    kaji_ldap_ca_file: str = ""
    kaji_ldap_base_dn: str = ""
    kaji_ldap_bind_dn: str = ""
    kaji_ldap_bind_password: str = ""
    kaji_ldap_user_filter: str = "(&(objectClass=person)(uid={username}))"
    kaji_ldap_username_attr: str = "uid"
    kaji_ldap_timeout: int = 5
    kaji_ldap_auto_create: bool = False
    kaji_ldap_default_role: str = "viewer"
    kaji_ldap_groups_attr: str = "memberOf"         # attribut de l'entrée qui liste les groupes (DN complets) ; Active Directory : memberOf (groupes DIRECTS seulement)
    kaji_ldap_admin_group: str = ""                 # DN du groupe dont les membres sont administrateurs de Kaji (vide : aucune correspondance, rôles inchangés) ; correspondance exacte
    kaji_ldap_operator_group: str = ""              # DN du groupe dont les membres sont opérateurs
    kaji_ldap_allow_admin: bool = True           # idem SSO : un administrateur existant peut se connecter par l'annuaire ; `false` les réserve au mot de passe local
    kaji_ldap_label: str = "Annuaire"
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
    # Création de jetons Proxmox par l'administrateur (lot #442) : l'expiration est OBLIGATOIRE, dans le futur, et au plus N jours (0 = facultative, comme avant le jalon J2).
    kaji_token_create_max_days: int = 365
    # Requêtes HTTP simultanées au plus (hors santé et flux temps réel) ; au-delà : 503 tout de suite (`app/limits.py`). 0 = pas de limite. Doit rester sous la taille du pool de connexions à la base
    # (`app/db.py`, 150) : le défaut laisse de la marge.
    kaji_max_concurrent_requests: int = 100
    # JETON DE SERVICE (lot #441) : le planificateur d'actions et les alertes tournent sans personne de connecté ; ils utilisent, par connexion, un jeton LIMITÉ aux droits dont ils ont besoin
    # (jamais Administrator) au lieu du jeton partagé. `true` : sans jeton de service, ils ne font RIEN pour cette connexion (au lieu de se rabattre sur le jeton partagé).
    kaji_require_service_token: bool = False
    kaji_service_token_max_days: int = 365

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
