from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from adscontrol.counters import CounterEnergy, DeviceHistory, counter_since

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
    # The last hour is still in progress (no reading after it yet), so it isn't stored.
    assert len([k for k in rows if k[1] == 1]) == 2


async def test_rerunning_updates_rows_without_doubling(engine, session, clean):
    job = CounterEnergy(async_sessionmaker(engine))
    await _readings(session, START, minutes=30, wh_start=1000)
    await job.run()
    await _readings(session, START + timedelta(minutes=30), minutes=40, wh_start=1180)
    await job.run()
    assert (await _rows(session))[(START, 1)] == (359.0, "counter")


async def test_device_rows_are_left_alone(engine, session, clean):
    await session.execute(
        text("INSERT INTO channel_energy VALUES (:h, 1, 999, 'device')"), {"h": START}
    )
    await session.commit()
    await _readings(session, START, minutes=70, wh_start=1000)
    await CounterEnergy(async_sessionmaker(engine)).run()
    assert (await _rows(session))[(START, 1)] == (999.0, "device")


class _History:
    def __init__(self, hours):
        self.hours = hours
        self.asked: list[int] = []

    async def read_hourly(self, channel, now=None):
        self.asked.append(channel)
        return self.hours


def _device_job(engine, client) -> DeviceHistory:
    async def discover(host):
        return "uuid"

    return DeviceHistory(
        "host",
        async_sessionmaker(engine),
        discover=discover,
        make_client=lambda host, uuid: client,
        pause_s=0,
    )


async def test_device_hours_replace_counter_and_spread_rows(engine, session, clean):
    await session.execute(
        text("INSERT INTO channel_energy VALUES (:h, 1, 120, 'spread')"), {"h": START}
    )
    await session.commit()
    client = _History([(START, 500)])
    await _device_job(engine, client).run()
    assert (await _rows(session))[(START, 1)] == (500.0, "device")
    assert client.asked == list(range(1, 19))


async def test_device_values_are_stored_raw(engine, session, clean):
    """Channel 17 is the water heater, multiplier 2; storage stays raw like consume_wh."""
    await _device_job(engine, _History([(START, 339)])).run()
    assert (await _rows(session))[(START, 17)] == (339.0, "device")


async def test_the_hour_still_in_progress_isnt_stored(engine, session, clean):
    """If recording stops mid-hour, a stored partial hour would pass for a complete one."""
    job = CounterEnergy(async_sessionmaker(engine))
    await _readings(session, START, minutes=30, wh_start=1000)
    await job.run()
    assert (START, 1) not in await _rows(session)
    await _readings(session, START + timedelta(hours=1), minutes=1, wh_start=1400)
    await job.run()
    assert (await _rows(session))[(START, 1)][0] > 0


async def test_device_rows_ahead_dont_send_the_job_back_48_hours(session, clean):
    """While recording is down the hourly history fills later hours; start from the latest row."""
    await session.execute(
        text("INSERT INTO channel_energy VALUES (:a, 1, 100, 'counter'), (:b, 1, 100, 'device')"),
        {"a": START, "b": START + timedelta(hours=40)},
    )
    await session.commit()
    assert await counter_since(session, 1) == START + timedelta(hours=40)


async def test_with_no_counter_rows_the_job_backfills_from_the_first_reading(session, clean):
    await session.execute(
        text("INSERT INTO channel_energy VALUES (:b, 1, 100, 'device')"),
        {"b": START + timedelta(hours=40)},
    )
    await session.commit()
    await _readings(session, START, minutes=1, wh_start=1000)
    assert await counter_since(session, 1) == START


async def test_an_outage_longer_than_the_device_history_is_still_spread(engine, session, clean):
    """Down for 100 h: the monitor's history covers only the last 48, the counter gap covers the
    rest, and nothing already stored is touched."""
    job = CounterEnergy(async_sessionmaker(engine))
    await _readings(session, START, minutes=70, wh_start=1000)
    await job.run()
    for h in range(52, 100):
        await session.execute(
            text("INSERT INTO channel_energy VALUES (:h, 1, 50, 'device')"),
            {"h": START + timedelta(hours=h)},
        )
    await session.commit()
    await _readings(session, START + timedelta(hours=100), minutes=2, wh_start=11_000, channels=(1,))
    await job.run()
    rows = await _rows(session)
    assert rows[(START + timedelta(hours=10), 1)][1] == "spread"
    assert rows[(START + timedelta(hours=60), 1)] == (50.0, "device")
    assert rows[(START, 1)] == (359.0, "counter")
