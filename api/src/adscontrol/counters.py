"""Hourly energy from the monitor's own running counters, so gaps in recording don't lose energy.

Each reading carries consume_wh, a per-channel running total that resets at local midnight on the
1st of each month. The difference between readings is exact energy whatever happened in between.
"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from adscontrol.refoss.client import CHANNEL_COUNT, RefossClient, RefossError, discover_uuid
from adscontrol.refoss.recorder import known_uuid

log = logging.getLogger(__name__)

HOUR = timedelta(hours=1)
DEVICE_HISTORY_INTERVAL_S = 3600  # the monitor keeps 48 hours, so hourly reads miss nothing
COUNTER_ENERGY_INTERVAL_S = 60
GAP_S = 60  # readings come every 10 s; anything wider is a gap whose energy gets spread


def _hour_of(t: datetime) -> datetime:
    return t.replace(minute=0, second=0, microsecond=0)


def _seconds_per_hour(t0: datetime, t1: datetime):
    hour = _hour_of(t0)
    while hour < t1:
        start, end = max(t0, hour), min(t1, hour + HOUR)
        if end > start:
            yield hour, (end - start).total_seconds()
        hour += HOUR


def hourly_from_counter(
    points: list[tuple[datetime, int]], gap_s: float = GAP_S
) -> dict[datetime, tuple[float, bool]]:
    """Wh per hour start from (time, consume_wh) points of one channel, oldest first.

    Each delta belongs to the hour of the later reading. A drop means the monthly reset: counting
    restarted at 0, so the delta is the new value. Across a gap the delta is spread over the hours
    it spans by time; those hours are marked spread.
    """
    wh: dict[datetime, float] = defaultdict(float)
    spread: dict[datetime, bool] = defaultdict(bool)
    for (t0, w0), (t1, w1) in pairwise(points):
        delta = w1 - w0 if w1 >= w0 else w1
        span = (t1 - t0).total_seconds()
        if span <= gap_s:
            wh[_hour_of(t1)] += delta
            spread.setdefault(_hour_of(t1), False)
            continue
        for hour, seconds in _seconds_per_hour(t0, t1):
            wh[hour] += delta * seconds / span
            spread[hour] = True
    return {hour: (wh[hour], spread[hour]) for hour in wh}


_LATEST = text("SELECT max(hour) FROM channel_energy WHERE channel = :c AND source <> 'device'")
_EARLIEST = text("SELECT min(time) FROM channel_readings WHERE channel = :c")
_BEFORE = text(
    "SELECT time, consume_wh FROM channel_readings WHERE channel = :c AND time < :s "
    "ORDER BY time DESC LIMIT 1"
)
_SINCE = text(
    "SELECT time, consume_wh FROM channel_readings WHERE channel = :c AND time >= :s ORDER BY time"
)
_UPSERT = text(
    """
    INSERT INTO channel_energy (hour, channel, wh, source) VALUES (:hour, :channel, :wh, :source)
    ON CONFLICT (hour, channel) DO UPDATE SET wh = EXCLUDED.wh, source = EXCLUDED.source
    WHERE channel_energy.source <> 'device'
    """
)


class CounterEnergy:
    """Keeps channel_energy current from the readings; the first run backfills everything stored."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def run(self) -> None:
        async with self._sessions() as session:
            for channel in range(1, CHANNEL_COUNT + 1):
                since = await session.scalar(_LATEST, {"c": channel}) or await session.scalar(
                    _EARLIEST, {"c": channel}
                )
                if since is None:
                    continue
                since = _hour_of(since)
                before = (await session.execute(_BEFORE, {"c": channel, "s": since})).first()
                rows = (await session.execute(_SINCE, {"c": channel, "s": since})).all()
                points = ([tuple(before)] if before else []) + [tuple(r) for r in rows]
                hours = hourly_from_counter(points)
                values = [
                    {
                        "hour": h,
                        "channel": channel,
                        "wh": wh,
                        "source": "spread" if s else "counter",
                    }
                    for h, (wh, s) in hours.items()
                    if h >= since
                ]
                if values:
                    await session.execute(_UPSERT, values)
            await session.commit()


_DEVICE_UPSERT = text(
    """
    INSERT INTO channel_energy (hour, channel, wh, source) VALUES (:hour, :channel, :wh, 'device')
    ON CONFLICT (hour, channel) DO UPDATE SET wh = EXCLUDED.wh, source = 'device'
    """
)


class DeviceHistory:
    """Copies the monitor's own hourly history over our hours: exact, and it covers our outages."""

    def __init__(
        self,
        host: str,
        sessions: async_sessionmaker[AsyncSession],
        *,
        discover: Callable[[str], Awaitable[str]] = discover_uuid,
        make_client: Callable[[str, str], RefossClient] = RefossClient,
        uuid_path: Path | None = None,
        pause_s: float = 1.0,
    ) -> None:
        self._host = host
        self._sessions = sessions
        self._discover = discover
        self._make_client = make_client
        self._uuid_path = uuid_path
        self._pause_s = pause_s

    async def run(self) -> None:
        client = self._make_client(
            self._host, await known_uuid(self._host, self._uuid_path, self._discover)
        )
        async with self._sessions() as session:
            for channel in range(1, CHANNEL_COUNT + 1):
                try:
                    hours = await client.read_hourly(channel)
                except RefossError as exc:  # one channel's miss shouldn't cost the rest
                    log.warning("hourly history for channel %s: %s", channel, exc)
                    continue
                if hours:
                    await session.execute(
                        _DEVICE_UPSERT,
                        [{"hour": h, "channel": channel, "wh": wh} for h, wh in hours],
                    )
                await asyncio.sleep(self._pause_s)
            await session.commit()
