"""Shared fixtures: a Timescale container (or TEST_DATABASE_URL), migrations, truncation."""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from adscontrol.db.migrate import upgrade_head


@pytest.fixture(scope="session")
def pg_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield url
        return
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer(
        "timescale/timescaledb:2.30.2-pg16", username="test", password="test", dbname="test"
    ) as pg:
        host = pg.get_container_host_ip()
        port = pg.get_exposed_port(5432)
        yield f"postgresql+psycopg://test:test@{host}:{port}/test"


@pytest.fixture(scope="session")
def migrated_db(pg_url: str) -> str:
    upgrade_head(pg_url)
    return pg_url


@pytest.fixture
async def engine(migrated_db):
    eng = create_async_engine(migrated_db, connect_args={"options": "-c timezone=UTC"})
    async with eng.begin() as conn:
        await conn.execute(text("TRUNCATE channel_readings"))
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s


@pytest.fixture(scope="session")
def tiny_mp4() -> bytes:
    """A real 10-frame MP4, shaped like a doorbell preview clip."""
    import io

    import av

    buffer = io.BytesIO()
    with av.open(buffer, "w", format="mp4") as out:
        stream = out.add_stream("mpeg4", rate=10)
        stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
        for _ in range(10):
            frame = av.VideoFrame(64, 48, "yuv420p")
            for plane in frame.planes:
                plane.update(bytes([128]) * plane.buffer_size)
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    return buffer.getvalue()
