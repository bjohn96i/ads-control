from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from adscontrol.db.copy import NewerTarget, copy_data
from adscontrol.db.migrate import upgrade_head

pytestmark = pytest.mark.integration

START = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


@dataclass
class Db:
    url: str

    async def execute(self, sql: str, **params) -> None:
        engine = create_async_engine(self.url)
        async with engine.begin() as conn:
            await conn.execute(text(sql), params)
        await engine.dispose()

    async def scalar(self, sql: str, **params):
        engine = create_async_engine(self.url)
        async with engine.connect() as conn:
            value = await conn.scalar(text(sql), params)
        await engine.dispose()
        return value

    async def add_readings(self, after: datetime, minutes: int) -> None:
        await self.execute(
            """
            INSERT INTO channel_readings
            SELECT t, c, 500, 120, 4, 1, 0
            FROM generate_series(CAST(:a AS timestamptz),
                                 CAST(:a AS timestamptz) + make_interval(mins => :m),
                                 INTERVAL '10 seconds') AS t,
                 (VALUES (1), (7)) AS ch(c)
            ON CONFLICT DO NOTHING
            """,
            a=after,
            m=minutes,
        )


def _fresh(pg_url: str, name: str) -> Db:
    engine = create_engine(pg_url.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {name}"))
    engine.dispose()
    url = pg_url.rsplit("/", 1)[0] + f"/{name}"
    db_engine = create_engine(url, isolation_level="AUTOCOMMIT")
    with db_engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
    db_engine.dispose()
    upgrade_head(url)
    return Db(url)


@pytest.fixture
async def source(pg_url) -> Db:
    db = _fresh(pg_url, "copy_source")
    await db.execute("UPDATE zones SET multiplier = 2 WHERE name = 'Water Heater'")
    await db.execute("INSERT INTO tasks (id, name, category) VALUES (5, 'Filters', 'House')")
    await db.execute("INSERT INTO completions (task_id, done_on) VALUES (5, '2026-11-01')")
    await db.execute(
        "INSERT INTO cameras (device_id, name, kind) VALUES ('d1', 'Back door', 'camera')"
    )
    await db.execute(
        "INSERT INTO camera_events (camera_id, type, occurred_at, event_id) "
        "SELECT id, 'motion', :t, 'e1' FROM cameras",
        t=START,
    )
    await db.execute("INSERT INTO outdoor_readings (time, temp_c) VALUES (:t, 18)", t=START)
    await db.execute(
        "INSERT INTO thermostat_readings (time, thermostat_id, ambient_c) VALUES (:t, 1, 21)",
        t=START,
    )
    await db.add_readings(START, minutes=120)
    return db


@pytest.fixture
async def target(pg_url) -> Db:
    return _fresh(pg_url, "copy_target")


async def _count(db: Db, table: str) -> int:
    return await db.scalar(f"SELECT count(*) FROM {table}")


async def test_full_copy_moves_every_table_and_replaces_seed_rows(source, target):
    counts = await copy_data(source.url, target.url, since=None)
    assert await target.scalar("SELECT multiplier FROM zones WHERE name = 'Water Heater'") == 2
    assert counts["channel_readings"] == await _count(source, "channel_readings")
    for table in (
        "zones",
        "tasks",
        "completions",
        "cameras",
        "camera_events",
        "outdoor_readings",
        "thermostat_readings",
        "rate_versions",
    ):
        assert await _count(target, table) == await _count(source, table), table


async def test_running_the_full_copy_twice_leaves_one_copy(source, target):
    await copy_data(source.url, target.url, since=None)
    await copy_data(source.url, target.url, since=None)
    assert await _count(target, "channel_readings") == await _count(source, "channel_readings")
    assert await _count(target, "zones") == await _count(source, "zones")


async def test_final_pass_adds_only_new_readings_once(source, target):
    await copy_data(source.url, target.url, since=None)
    cut = await source.scalar("SELECT max(time) FROM channel_readings") - timedelta(minutes=5)
    await source.add_readings(after=cut, minutes=10)  # overlaps 5 copied minutes
    await source.execute("UPDATE zones SET multiplier = 3 WHERE name = 'Dryer'")  # edited meanwhile
    await copy_data(source.url, target.url, since=cut)
    assert await _count(target, "channel_readings") == await _count(source, "channel_readings")
    assert await target.scalar("SELECT multiplier FROM zones WHERE name = 'Dryer'") == 3
    # The final pass must not wipe history that predates it.
    assert await _count(target, "camera_events") == 1


async def test_new_rows_after_the_copy_do_not_collide(source, target):
    await copy_data(source.url, target.url, since=None)
    await target.execute("INSERT INTO tasks (name, category) VALUES ('New', 'House')")
    # The copied task is id 5; an unmoved sequence would have handed out 1.
    assert await target.scalar("SELECT id FROM tasks WHERE name = 'New'") > 5
    await target.execute(
        "INSERT INTO cameras (device_id, name, kind) VALUES ('d2', 'Front', 'camera')"
    )


async def test_charts_cover_the_copied_history(source, target):
    await copy_data(source.url, target.url, since=None)
    assert await _count(target, "channel_hourly") > 0
    assert await _count(target, "channel_daily") > 0


async def test_final_pass_mirrors_a_completion_undone_and_redone(source, target):
    """Unticking and re-ticking a task between passes deletes one row and adds another for the
    same day; the final pass must carry the delete too, or the add breaks completions_once."""
    await copy_data(source.url, target.url, since=None)
    await source.execute("DELETE FROM completions WHERE task_id = 5")
    await source.execute("INSERT INTO completions (task_id, done_on) VALUES (5, '2026-11-01')")
    cut = await source.scalar("SELECT max(time) FROM channel_readings")
    await copy_data(source.url, target.url, since=cut)
    assert await target.scalar("SELECT array_agg(id) FROM completions") == await source.scalar(
        "SELECT array_agg(id) FROM completions"
    )


async def test_a_late_camera_event_is_still_carried_over(source, target):
    """Events are stored when they arrive, stamped when they happened; the final pass mustn't
    skip one that arrived late with an earlier timestamp."""
    await copy_data(source.url, target.url, since=None)
    await source.execute(
        "INSERT INTO camera_events (camera_id, type, occurred_at, event_id) "
        "SELECT id, 'person', :t, 'late' FROM cameras",
        t=START - timedelta(hours=1),
    )
    await copy_data(source.url, target.url, since=START + timedelta(hours=2))
    assert await target.scalar("SELECT count(*) FROM camera_events WHERE event_id = 'late'") == 1


async def test_a_full_copy_wont_overwrite_a_newer_database(source, target):
    """Run the wrong way round (or again after cutover), it would wipe newer readings."""
    await target.add_readings(after=START + timedelta(days=1), minutes=1)
    with pytest.raises(NewerTarget):
        await copy_data(source.url, target.url, since=None)
    await copy_data(source.url, target.url, since=None, force=True)
