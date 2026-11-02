"""What the house is doing right now. A stopped feed answers null, never 0 W."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Request
from sqlalchemy import text

from adscontrol.energy import energy_by_zone
from adscontrol.rates import LOCAL, all_in_cents, rate_for, rate_period
from adscontrol.zones import list_zones, zone_power

STALE_AFTER_S = 30

router = APIRouter()

_LATEST = text(
    """
    SELECT DISTINCT ON (channel) channel, time, power_w FROM channel_readings
    WHERE time > :since AND time <= :now
    ORDER BY channel, time DESC
    """
)


def _month_start(now: datetime) -> datetime:
    return now.astimezone(LOCAL).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


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
    return {
        "as_of": as_of,
        "stale": stale,
        "whole_house_w": whole,
        "unmetered_w": unmetered,
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
                "flagged": False,
            }
            for z in circuits
        ],
        "month_kwh": month_whole.kwh if month_whole else 0.0,
        "month_coverage": month_whole.coverage if month_whole else 0.0,
    }
