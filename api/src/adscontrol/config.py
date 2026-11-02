"""Settings from the environment and the git-ignored .env."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", ROOT_DIR / "api" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://adscontrol:adscontrol@localhost:5432/adscontrol"
    refoss_host: str = "192.168.4.254"
    bind_host: str = "127.0.0.1"
    port: int = 8100


@lru_cache
def get_settings() -> Settings:
    return Settings()
