"""What the house is doing right now. A stopped feed answers null, never 0 W."""

from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Request
from sqlalchemy import text

from adscontrol.detect.store import open_findings
from adscontrol.energy import CHARGER_MIN_W, energy_by_zone
from adscontrol.rates import LOCAL, all_in_cents, rate_for, rate_period
from adscontrol.zones import list_zones, zone_power

STALE_AFTER_S = 30
# The charger has no sensor of its own, so it is inferred: a large load on the incoming lines
# that no zone explains, held long enough that it is not an A/C or motor starting up.
CHARGER_WINDOW = timedelta(seconds=35)
CHARGER_MIN_SAMPLES = 3
OUTDOOR_STALE = timedelta(hours=3)
RECENT_LINE = timedelta(hours=1)

router = APIRouter()

_LATEST = text(
    """
    SELECT DISTINCT ON (channel) channel, time, power_w FROM channel_readings
    WHERE time > :since AND time <= :now
    ORDER BY channel, time DESC
    """
)


_RECENT = text(
    """
    SELECT time, channel, power_w FROM channel_readings WHERE time > :since AND time <= :now
    """
)


_OUTDOOR = text(
    "SELECT time, temp_c FROM outdoor_readings WHERE time <= :now ORDER BY time DESC LIMIT 1"
)

# Each sample's incoming channels summed first, then averaged per minute.
_LINE = text(
    """
    SELECT time_bucket('1 minute', time) AS minute, avg(watts) AS watts FROM (
        SELECT time, sum(power_w) AS watts FROM channel_readings
        WHERE channel = ANY(:channels) AND time > :since AND time <= :now GROUP BY time
    ) samples GROUP BY 1 ORDER BY 1
    """
)


def _charger_estimate(rows, zones) -> float:
    by_time: dict[datetime, dict[int, float]] = defaultdict(dict)
    for row in rows:
        by_time[row.time][row.channel] = row.power_w
    unexplained = []
    for by_channel in by_time.values():
        powers = {z.kind: 0.0 for z in zones}
        for z in zones:
            powers[z.kind] += zone_power(z, by_channel) or 0.0
        unexplained.append(powers["incoming"] - powers["circuit"])
    if len(unexplained) < CHARGER_MIN_SAMPLES or min(unexplained) < CHARGER_MIN_W:
        return 0.0
    return sum(unexplained) / len(unexplained)


def _month_start(now: datetime) -> datetime:
    return now.astimezone(LOCAL).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _day_start(now: datetime) -> datetime:
    return now.astimezone(LOCAL).replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/api/live")
async def live(request: Request) -> dict:
    now: datetime = request.app.state.clock()
    async with request.app.state.sessions() as session:
        rows = (
            await session.execute(_LATEST, {"since": now - timedelta(hours=1), "now": now})
        ).all()
        zones = await list_zones(session)
        rate = await rate_for(session, now.astimezone(LOCAL).date())
        month = await energy_by_zone(session, _month_start(now), now)
        flags = await open_findings(session)
        recent = (await session.execute(_RECENT, {"since": now - CHARGER_WINDOW, "now": now})).all()
        today = await energy_by_zone(session, _day_start(now), now)
        outdoor = (await session.execute(_OUTDOOR, {"now": now})).first()
        incoming = next((z for z in zones if z.kind == "incoming"), None)
        line = (
            []
            if incoming is None
            else (
                await session.execute(
                    _LINE,
                    {"channels": incoming.channels, "since": now - RECENT_LINE, "now": now},
                )
            ).all()
        )

    as_of = max((r.time for r in rows), default=None)
    stale = as_of is None or (now - as_of).total_seconds() > STALE_AFTER_S
    by_channel = {} if stale else {r.channel: r.power_w for r in rows}

    circuits = [z for z in zones if z.kind == "circuit"]
    whole = next((zone_power(z, by_channel) for z in zones if z.kind == "incoming"), None)
    watts = {z.id: zone_power(z, by_channel) for z in circuits}
    # Clamp noise and multipliers can push zones past the mains; that is not negative power.
    unmetered = (
        None
        if whole is None or any(w is None for w in watts.values())
        else max(0.0, whole - sum(watts.values()))
    )
    period = rate_period(now)
    month_whole = next((e for e in month if e.name == "Whole House"), None)
    today_whole = next((e for e in today if e.name == "Whole House"), None)
    fresh_outdoor = outdoor is not None and now - outdoor.time <= OUTDOOR_STALE
    return {
        "as_of": as_of,
        "stale": stale,
        "whole_house_w": whole,
        "unmetered_w": unmetered,
        "charger_estimate_w": None if stale else _charger_estimate(recent, zones),
        "cost_per_hour_estimate": (
            None if whole is None else whole / 1000 * all_in_cents(rate, period) / 100
        ),
        "rate_period": period,
        "zones": [
            {
                "id": z.id,
                "name": z.name,
                "watts": watts[z.id],
                "pin_x": z.pin_x,
                "pin_y": z.pin_y,
                "room": z.room,
                "floor": z.floor,
                "flagged": bool(flags.get(z.id)),
            }
            for z in circuits
        ],
        "month_kwh": month_whole.kwh if month_whole else 0.0,
        "month_coverage": month_whole.coverage if month_whole else 0.0,
        "outdoor_f": outdoor.temp_c * 9 / 5 + 32 if fresh_outdoor else None,
        "today_kwh": today_whole.kwh if today_whole else 0.0,
        "today_cost": today_whole.est_cost if today_whole else 0.0,
        "today_coverage": today_whole.coverage if today_whole else 0.0,
        "recent_w": [
            {"time": r.minute, "watts": r.watts * (incoming.multiplier if incoming else 1)}
            for r in line
        ],
    }
