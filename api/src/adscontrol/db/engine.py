"""Async engine and session factory (SQLAlchemy 2.0 + psycopg 3)."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(database_url: str) -> AsyncEngine:
    # UTC on every connection: bucketing must not depend on where the process runs.
    return create_async_engine(
        database_url, pool_pre_ping=True, connect_args={"options": "-c timezone=UTC"}
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
