from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    kaji_secret_key: str
    database_url: str = "sqlite:///./kaji.db"
    # Cookie de session « Secure » : mettre false uniquement en HTTP non-localhost
    kaji_cookie_secure: bool = True
    kaji_session_hours: int = 12
    # Derrière un reverse proxy : prend l'IP ajoutée par le proxy (dernière valeur de X-Forwarded-For) pour le
    # limiteur de connexions. À n'activer QUE derrière un proxy de confiance : sinon l'en-tête est falsifiable.
    kaji_trust_proxy: bool = False
    # Les entrées d'audit plus anciennes sont supprimées (0 = conserver indéfiniment)
    kaji_audit_retention_days: int = 365
    # Identifiants de machines que Kaji refuse de supprimer, quoi qu'il arrive (ex. "105,108")
    kaji_protected_vmids: str = ""

    @property
    def protected_vmids(self) -> set[int]:
        return {int(x) for x in self.kaji_protected_vmids.replace(" ", "").split(",") if x.isdigit()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
