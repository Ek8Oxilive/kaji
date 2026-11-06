from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    pud_secret_key: str
    database_url: str = "sqlite:///./pud.db"


def get_settings() -> Settings:
    return Settings()
