"""Energy per zone from recorded power, with coverage so gaps never read as low usage."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from adscontrol.rates import rate_period
from adscontrol.refoss.recorder import SAMPLE_INTERVAL_S
from adscontrol.zones import list_zones

RAW_RANGE_LIMIT = timedelta(days=1)

_RAW = text(
    """
    SELECT time_bucket('1 hour', time) AS bucket, channel, avg(power_w) AS avg_w, count(*) AS samples
    FROM channel_readings WHERE time >= :start AND time < :end GROUP BY 1, 2
    """
)
_HOURLY = text(
    """
    SELECT bucket, channel, avg_w, samples FROM channel_hourly
    WHERE bucket >= :start AND bucket < :end
    """
)


@dataclass(frozen=True)
class ZoneEnergy:
    zone_id: int
    name: str
    kwh: float
    coverage: float
    by_period: dict[str, float] = field(default_factory=dict)


def _zone_periods(
    by_period: dict[int, dict[str, float]], channels: list[int], multiplier: float
) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for channel in channels:
        for period, value in by_period[channel].items():
            totals[period] += value * multiplier
    return dict(totals)


async def energy_by_zone(session: AsyncSession, start: datetime, end: datetime) -> list[ZoneEnergy]:
    query = _RAW if end - start <= RAW_RANGE_LIMIT else _HOURLY
    rows = (await session.execute(query, {"start": start, "end": end})).all()

    kwh: dict[int, float] = defaultdict(float)
    samples: dict[int, int] = defaultdict(int)
    # Hour buckets are safe here: every period boundary falls on a whole local hour.
    by_period: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        row_kwh = row.avg_w * row.samples * SAMPLE_INTERVAL_S / 3_600_000
        kwh[row.channel] += row_kwh
        samples[row.channel] += row.samples
        by_period[row.channel][rate_period(row.bucket)] += row_kwh

    expected = (end - start).total_seconds() / SAMPLE_INTERVAL_S
    return [
        ZoneEnergy(
            zone_id=zone.id,
            name=zone.name,
            kwh=sum(kwh[c] for c in zone.channels) * zone.multiplier,
            coverage=min(1.0, min(samples[c] for c in zone.channels) / expected),
            by_period=_zone_periods(by_period, zone.channels, zone.multiplier),
        )
        for zone in await list_zones(session)
    ]
