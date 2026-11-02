"""Energy per zone from recorded power, with coverage so gaps never read as low usage."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from adscontrol.rates import LOCAL, all_in_cents, list_rates, rate_period, version_in_force
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
    est_cost: float = 0.0


def _zone_periods(
    by_period: dict[int, dict[str, float]], channels: list[int], multiplier: float
) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for channel in channels:
        for period, value in by_period[channel].items():
            totals[period] += value * multiplier
    return dict(totals)


async def energy_by_zone(session: AsyncSession, start: datetime, end: datetime) -> list[ZoneEnergy]:
    rates = await list_rates(session)
    cost: dict[int, float] = defaultdict(float)
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
        period = rate_period(row.bucket)
        by_period[row.channel][period] += row_kwh
        rate = version_in_force(rates, row.bucket.astimezone(LOCAL).date())
        cost[row.channel] += row_kwh * all_in_cents(rate, period) / 100

    expected = (end - start).total_seconds() / SAMPLE_INTERVAL_S
    return [
        ZoneEnergy(
            zone_id=zone.id,
            name=zone.name,
            kwh=sum(kwh[c] for c in zone.channels) * zone.multiplier,
            coverage=min(1.0, min(samples[c] for c in zone.channels) / expected),
            by_period=_zone_periods(by_period, zone.channels, zone.multiplier),
            est_cost=sum(cost[c] for c in zone.channels) * zone.multiplier,
        )
        for zone in await list_zones(session)
    ]


# The charger has no sensor, so it is inferred from load no zone explains. Five-minute buckets
# keep a short session from being averaged away by the hour it sits in.
CHARGER_MIN_W = 1500.0
_UNEXPLAINED = text(
    """
    WITH samples AS (
        SELECT time_bucket('5 minutes', r.time) AS bucket, r.channel, avg(r.power_w) AS avg_w, count(*) AS n
        FROM channel_readings r WHERE r.time >= :start AND r.time < :end GROUP BY 1, 2
    ), by_zone AS (
        SELECT s.bucket, z.kind, sum(s.avg_w * z.multiplier) AS watts, max(s.n) AS n
        FROM samples s JOIN zones z ON s.channel = ANY(z.channels) GROUP BY 1, 2
    )
    SELECT i.bucket, i.watts - coalesce(c.watts, 0) AS watts, i.n
    FROM by_zone i LEFT JOIN by_zone c ON c.bucket = i.bucket AND c.kind = 'circuit'
    WHERE i.kind = 'incoming' AND i.watts - coalesce(c.watts, 0) >= :minimum
    """
)


async def charger_estimate(
    session: AsyncSession, start: datetime, end: datetime
) -> tuple[float, float]:
    """Returns (kWh, estimated cost) for load that looks like the car charging."""
    rates = await list_rates(session)
    rows = await session.execute(
        _UNEXPLAINED, {"start": start, "end": end, "minimum": CHARGER_MIN_W}
    )
    kwh = cost = 0.0
    for row in rows:
        bucket_kwh = row.watts * row.n * SAMPLE_INTERVAL_S / 3_600_000
        rate = version_in_force(rates, row.bucket.astimezone(LOCAL).date())
        kwh += bucket_kwh
        cost += bucket_kwh * all_in_cents(rate, rate_period(row.bucket)) / 100
    return kwh, cost
