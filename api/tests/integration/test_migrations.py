from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text

from adscontrol.db.migrate import API_DIR
from alembic import command

pytestmark = pytest.mark.integration


def _config(url: str) -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def test_every_migration_downgrades_and_upgrades_again(pg_url):
    admin = create_engine(pg_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS roundtrip WITH (FORCE)"))
        conn.execute(text("CREATE DATABASE roundtrip"))
    url = pg_url.rsplit("/", 1)[0] + "/roundtrip"
    try:
        command.upgrade(_config(url), "head")
        command.downgrade(_config(url), "base")
        command.upgrade(_config(url), "head")
    finally:
        with admin.connect() as conn:
            conn.execute(text("DROP DATABASE IF EXISTS roundtrip WITH (FORCE)"))
        admin.dispose()


def test_migrations_do_not_import_app_code():
    """App constants change; a migration must do the same thing on a fresh database forever."""
    for path in (Path(API_DIR) / "alembic" / "versions").glob("*.py"):
        assert "from adscontrol" not in path.read_text(), path.name
