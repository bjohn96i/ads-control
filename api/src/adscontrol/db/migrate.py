"""Run Alembic programmatically."""

from pathlib import Path

from alembic.config import Config

from alembic import command

API_DIR = Path(__file__).resolve().parents[3]


def upgrade_head(database_url: str) -> None:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
