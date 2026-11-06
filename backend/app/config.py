from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    kaji_secret_key: str
    database_url: str = "sqlite:///./kaji.db"


def get_settings() -> Settings:
    return Settings()
