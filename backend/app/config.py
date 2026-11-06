from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    kaji_secret_key: str
    database_url: str = "sqlite:///./kaji.db"
    # Cookie de session « Secure » : mettre false uniquement en HTTP non-localhost
    kaji_cookie_secure: bool = True
    kaji_session_hours: int = 12


@lru_cache
def get_settings() -> Settings:
    return Settings()
