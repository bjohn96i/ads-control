"""Settings from the environment and the git-ignored .env."""

import re
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]


class MisenteredSetting(Exception):
    """A setting whose value repeats its own name. Not a ValueError on purpose: pydantic would wrap
    that with every setting's value, secrets included, in the message."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", ROOT_DIR / "api" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        # Compose passes an unset ${VAR} as "", which would crash a list or number setting.
        env_ignore_empty=True,
    )

    database_url: str = "postgresql+psycopg://adscontrol:adscontrol@localhost:5432/adscontrol"
    refoss_host: str = "192.168.4.254"
    bind_host: str = "0.0.0.0"  # phones on the home Wi-Fi use the maintenance page
    port: int = 8100
    # Hostnames this server answers to; anything else is refused, which stops a DNS-rebinding page
    # from reading the API. Each install lists its LAN IP and .local name in ALLOWED_HOSTS in .env.
    allowed_hosts: list[str] = ["localhost"]
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
    # While this file exists the recorder jobs stay off, so a new deployment can wait for cutover.
    hold_path: Path = ROOT_DIR / "data" / "hold"
    refoss_uuid_path: Path = ROOT_DIR / "data" / "refoss_uuid"
    lanthorn_url: str = (
        "http://localhost:8000"  # the sister network app; browsers open its links too
    )

    @model_validator(mode="before")
    @classmethod
    def no_value_repeats_its_name(cls, data: dict) -> dict:
        # The Portainer form once got REFOSS_HOST=REFOSS_HOST=…, which stopped recording silently.
        for key, value in (data or {}).items():
            if isinstance(value, str) and value.upper().startswith(f"{key.upper()}="):
                raise MisenteredSetting(f"{key.upper()} repeats its own name; enter only the value")
        return data

    @field_validator("refoss_host")
    @classmethod
    def refoss_host_is_an_address(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9.-]+", value):
            raise ValueError("REFOSS_HOST must be an IP address or host name, e.g. 192.168.4.254")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
