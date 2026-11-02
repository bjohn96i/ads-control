"""Alembic environment: sync psycopg engine, URL from Settings unless overridden."""

from sqlalchemy import create_engine, pool

from adscontrol.config import get_settings
from alembic import context

config = context.config


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
