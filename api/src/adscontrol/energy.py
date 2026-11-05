"""Energy per zone, with coverage so gaps never read as low usage.

Each channel-hour uses the monitor's counter energy (channel_energy) when there is a row for it,
which is exact even across recording gaps, and otherwise the 10-second power samples.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

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


# Only hours wholly inside the range: a partial hour at either end (the current one, say) keeps
# using its samples, which are fresher than the counter job's last run.
_COUNTER = text(
    """
    SELECT hour, channel, wh FROM channel_energy
    WHERE hour >= :start AND hour + INTERVAL '1 hour' <= :end
    """
)
SAMPLES_PER_HOUR = 3600 / SAMPLE_INTERVAL_S


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
    counted = {
        (r.hour, r.channel): r.wh
        for r in await session.execute(_COUNTER, {"start": start, "end": end})
    }

    kwh: dict[int, float] = defaultdict(float)
    samples: dict[int, float] = defaultdict(float)
    # Hour buckets are safe here: every period boundary falls on a whole local hour.
    by_period: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    def add(hour: datetime, channel: int, row_kwh: float, row_samples: float) -> None:
        kwh[channel] += row_kwh
        samples[channel] += row_samples
        period = rate_period(hour)
        by_period[channel][period] += row_kwh
        rate = version_in_force(rates, hour.astimezone(LOCAL).date())
        cost[channel] += row_kwh * all_in_cents(rate, period) / 100

    for row in rows:
        if (row.bucket, row.channel) not in counted:
            add(
                row.bucket,
                row.channel,
                row.avg_w * row.samples * SAMPLE_INTERVAL_S / 3_600_000,
                row.samples,
            )
    for (hour, channel), wh in counted.items():
        add(hour, channel, wh / 1000, SAMPLES_PER_HOUR)  # a counter hour is a fully covered hour

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


async def add_manual_day(
    session: AsyncSession, day: date, kwh: float, source: str = "Refoss app"
) -> None:
    """A whole-house daily total from before recording began; entering a day again replaces it."""
    await session.execute(
        text(
            "INSERT INTO manual_daily_energy (day, kwh, source) VALUES (:d, :k, :s) "
            "ON CONFLICT (day) DO UPDATE SET kwh = EXCLUDED.kwh, source = EXCLUDED.source"
        ),
        {"d": day, "k": kwh, "s": source},
    )


async def manual_days(session: AsyncSession, start: date, end: date) -> dict[date, float]:
    """Hand-entered whole-house days from start to end inclusive, leaving out any day that has
    whole-house energy data of its own (measured beats remembered)."""
    channels = await session.scalar(text("SELECT channels FROM zones WHERE kind = 'incoming'"))
    rows = await session.execute(
        text(
            """
            SELECT day, kwh FROM manual_daily_energy m
            WHERE day BETWEEN :start AND :end
              AND NOT EXISTS (SELECT 1 FROM channel_energy e WHERE e.channel = ANY(:ch)
                  AND (e.hour AT TIME ZONE 'America/New_York')::date = m.day)
              AND NOT EXISTS (SELECT 1 FROM channel_hourly h WHERE h.channel = ANY(:ch)
                  AND h.bucket >= m.day::timestamp AT TIME ZONE 'America/New_York'
                  AND h.bucket < (m.day + 1)::timestamp AT TIME ZONE 'America/New_York')
            ORDER BY day
            """
        ),
        {"start": start, "end": end, "ch": channels or []},
    )
    return {r.day: r.kwh for r in rows}


def manual_share(manual: dict[date, float], start: datetime, end: datetime) -> tuple[float, float]:
    """kWh and days of hand-entered days inside [start, end), pro rata for a day cut by either end
    (a 7-day range starting at noon holds half of its first day)."""
    kwh = days = 0.0
    for day, value in manual.items():
        day_start = datetime.combine(day, time.min, tzinfo=LOCAL)
        day_end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=LOCAL)
        inside = (min(end, day_end) - max(start, day_start)).total_seconds()
        fraction = max(0.0, inside) / (day_end - day_start).total_seconds()
        kwh += value * fraction
        days += fraction
    return kwh, days
