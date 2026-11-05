from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from adscontrol.counters import CounterEnergy

pytestmark = pytest.mark.integration

START = datetime(2026, 11, 4, 10, tzinfo=timezone.utc)


async def _readings(session, start: datetime, minutes: int, wh_start: int, channels=(1, 7)):
    """One reading per 10 s; the counter rises 1 Wh per reading."""
    await session.execute(
        text(
            """
            INSERT INTO channel_readings
            SELECT CAST(:s AS timestamptz) + make_interval(secs => 10 * i), c, 360, 120, 3, 1, :w + i
            FROM generate_series(0, :n - 1) AS i, unnest(CAST(:c AS int[])) AS c
            """
        ),
        {"s": start, "n": minutes * 6, "w": wh_start, "c": list(channels)},
    )
    await session.commit()


async def _rows(session) -> dict:
    rows = await session.execute(text("SELECT hour, channel, wh, source FROM channel_energy"))
    return {(r.hour, r.channel): (r.wh, r.source) for r in rows}


@pytest.fixture
async def clean(session):
    await session.execute(text("TRUNCATE channel_energy"))
    await session.commit()


async def test_first_run_backfills_from_the_earliest_reading(engine, session, clean):
    await _readings(session, START, minutes=180, wh_start=1000)
    await CounterEnergy(async_sessionmaker(engine)).run()
    rows = await _rows(session)
    assert rows[(START, 1)] == (359.0, "counter")  # the first reading has nothing before it
    assert rows[(START + timedelta(hours=1), 7)] == (360.0, "counter")
    assert len([k for k in rows if k[1] == 1]) == 3


async def test_rerunning_updates_rows_without_doubling(engine, session, clean):
    job = CounterEnergy(async_sessionmaker(engine))
    await _readings(session, START, minutes=30, wh_start=1000)
    await job.run()
    await _readings(session, START + timedelta(minutes=30), minutes=30, wh_start=1180)
    await job.run()
    assert (await _rows(session))[(START, 1)] == (359.0, "counter")


async def test_device_rows_are_left_alone(engine, session, clean):
    await session.execute(
        text("INSERT INTO channel_energy VALUES (:h, 1, 999, 'device')"), {"h": START}
    )
    await session.commit()
    await _readings(session, START, minutes=60, wh_start=1000)
    await CounterEnergy(async_sessionmaker(engine)).run()
    assert (await _rows(session))[(START, 1)] == (999.0, "device")
