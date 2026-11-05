"""Settings from the environment and the git-ignored .env."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
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
    bind_host: str = "0.0.0.0"  # phones on the home Wi-Fi use the maintenance page
    port: int = 8100
    # The house's own names for this Mac (see deploy/Caddyfile). Anything else is refused, which stops a
    # DNS-rebinding page from reading the API; a new IP or name goes here (ALLOWED_HOSTS in .env).
    allowed_hosts: list[str] = [
        "localhost",
        "127.0.0.1",
        "192.168.4.41",
        "MacBook-Air-2.local",
        "control.home.arpa",
    ]
    household: list[
        str
    ] = []  # first names for "who's using this phone"; HOUSEHOLD in .env, a JSON list
    allow_insecure_pin: bool = False  # local development only; PIN and cameras then use plain HTTP
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    sdm_project_id: str = ""
    weather_lat: float | None = None
    weather_lon: float | None = None
    google_pubsub_subscription: str = ""
    nest_token_path: Path = ROOT_DIR / "data" / "nest_token"
    traffic_cameras_path: Path = ROOT_DIR / "data" / "traffic_cameras.yaml"
    lanthorn_url: str = (
        "http://localhost:8000"  # the sister network app; browsers open its links too
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
