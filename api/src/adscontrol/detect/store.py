"""Loads what the rules need and keeps one open finding per zone and kind."""

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from adscontrol.detect.rules import (
    BASELINE_DAYS,
    CREEP_PRIOR_DAYS,
    CREEP_RECENT_DAYS,
    CREEP_SUSTAINED_DAYS,
    Finding,
    HourSample,
    anomaly_finding,
    creep_finding,
)
from adscontrol.rates import LOCAL
from adscontrol.refoss.recorder import SAMPLE_INTERVAL_S
from adscontrol.zones import list_zones

RESOLVE_AFTER = timedelta(hours=24)
FULL_HOUR_SAMPLES = 3600 / SAMPLE_INTERVAL_S * 0.8  # a mostly-recorded hour
FULL_DAY_SAMPLES = 86400 / SAMPLE_INTERVAL_S * 0.9

_HOURLY = text(
    "SELECT bucket, channel, avg_w, samples FROM channel_hourly WHERE bucket >= :since AND bucket < :until"
)
_DAILY = text(
    "SELECT bucket, channel, avg_w, samples FROM channel_daily WHERE bucket >= :since AND bucket < :until"
)
_INSERT = text(
    """
    INSERT INTO findings (zone_id, kind, opened_at, last_seen, evidence)
    VALUES (:zone_id, :kind, :now, :now, :evidence)
    ON CONFLICT (zone_id, kind) WHERE resolved_at IS NULL
    DO UPDATE SET last_seen = :now, evidence = :evidence
    """
).bindparams(bindparam("evidence", type_=JSONB))


async def record_findings(
    session: AsyncSession, by_zone: dict[int, list[Finding]], now: datetime
) -> None:
    for zone_id, findings in by_zone.items():
        for finding in findings:
            await session.execute(
                _INSERT,
                {
                    "zone_id": zone_id,
                    "kind": finding.kind,
                    "now": now,
                    "evidence": {"summary": finding.summary, **finding.evidence},
                },
            )
    await session.execute(
        text(
            "UPDATE findings SET resolved_at = :now WHERE resolved_at IS NULL AND last_seen < :cut"
        ),
        {"now": now, "cut": now - RESOLVE_AFTER},
    )
    await session.commit()


async def run_detection(session: AsyncSession, now: datetime) -> None:
    last = now.replace(minute=0, second=0, microsecond=0)
    hourly = (
        await session.execute(
            _HOURLY, {"since": last - timedelta(days=BASELINE_DAYS), "until": last}
        )
    ).all()
    daily_days = CREEP_RECENT_DAYS + CREEP_PRIOR_DAYS + CREEP_SUSTAINED_DAYS
    daily = (
        await session.execute(
            _DAILY, {"since": last - timedelta(days=daily_days + 1), "until": last}
        )
    ).all()

    by_zone: dict[int, list[Finding]] = {}
    for zone in await list_zones(session):
        if zone.kind != "circuit":
            continue
        hours: dict[datetime, list[float]] = defaultdict(list)
        for row in hourly:
            if row.channel in zone.channels and row.samples >= FULL_HOUR_SAMPLES:
                hours[row.bucket].append(row.avg_w)
        samples = [
            HourSample(hour, sum(values) * zone.multiplier)
            for hour, values in hours.items()
            if len(values) == len(zone.channels)
        ]
        days: dict = defaultdict(float)
        counts: dict = defaultdict(int)
        for row in daily:
            if row.channel in zone.channels and row.samples >= FULL_DAY_SAMPLES:
                day = row.bucket.astimezone(LOCAL).date()
                days[day] += (
                    row.avg_w * row.samples * SAMPLE_INTERVAL_S / 3_600_000 * zone.multiplier
                )
                counts[day] += 1
        complete = {d: kwh for d, kwh in days.items() if counts[d] == len(zone.channels)}
        found = [anomaly_finding(samples, now), creep_finding(complete, seasonal=zone.seasonal)]
        by_zone[zone.id] = [f for f in found if f]
    await record_findings(session, by_zone, now)


async def open_findings(session: AsyncSession) -> dict[int, list[dict]]:
    rows = await session.execute(
        text(
            "SELECT zone_id, kind, opened_at, evidence FROM findings WHERE resolved_at IS NULL ORDER BY opened_at"
        )
    )
    result: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        result[row.zone_id].append(
            {"kind": row.kind, "opened_at": row.opened_at, "summary": row.evidence["summary"]}
        )
    return result
