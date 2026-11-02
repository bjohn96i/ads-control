"""The thermostats: what they report, how that lines up with power, and a person's changes."""

from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from adscontrol.api.maintenance import require_action
from adscontrol.auth import require_pin
from adscontrol.climate import CoolingDay, c_to_f, cooling_estimate, f_to_c
from adscontrol.energy import energy_by_zone
from adscontrol.nest.sdm import NestError, RateLimited
from adscontrol.nest.thermostat import list_paired
from adscontrol.rates import LOCAL, rate_period
from adscontrol.refoss.recorder import SAMPLE_INTERVAL_S

STALE_AFTER = timedelta(minutes=5)
ON_PEAK_FLAG_W = 500.0
ESTIMATE_DAYS = 120
Range = Literal["1d", "7d", "30d"]
_SPANS = {
    "1d": (timedelta(days=1), 900),
    "7d": (timedelta(days=7), 3600),
    "30d": (timedelta(days=30), 3600),
}

router = APIRouter(prefix="/api/climate")


class SetpointIn(BaseModel):
    temp_f: float = Field(ge=50, le=90)
    target: Literal["heat", "cool"] | None = None


def _f(c: float | None) -> float | None:
    return None if c is None else c_to_f(c)


def _setpoint_f(mode: str | None, heat_c: float | None, cool_c: float | None) -> float | None:
    return _f(cool_c if mode == "COOL" else heat_c if mode == "HEAT" else None)


async def _latest(session, thermostat_id: int):
    return (
        await session.execute(
            text(
                """
                SELECT * FROM thermostat_readings WHERE thermostat_id = :i
                ORDER BY time DESC LIMIT 1
                """
            ),
            {"i": thermostat_id},
        )
    ).first()


def _current(row, now: datetime) -> dict:
    stale = row is None or now - row.time > STALE_AFTER
    if stale:
        return {
            "stale": True,
            "ambient_f": None,
            "humidity": None,
            "setpoint_f": None,
            "heat_f": None,
            "cool_f": None,
            "mode": None,
            "hvac_status": None,
            "eco": False,
            "online": False,
        }
    return {
        "stale": False,
        "ambient_f": _f(row.ambient_c),
        "humidity": row.humidity,
        "setpoint_f": _setpoint_f(row.mode, row.heat_c, row.cool_c),
        "heat_f": _f(row.heat_c),
        "cool_f": _f(row.cool_c),
        "mode": row.mode,
        "hvac_status": row.hvac_status,
        "eco": row.eco,
        "online": row.online,
    }


@router.get("/summary")
async def summary(request: Request) -> dict:
    now: datetime = request.app.state.clock()
    async with request.app.state.sessions() as session:
        paired = await list_paired(session)
        rows = [(t, await _latest(session, t.id)) for t in paired]
    return {
        "thermostats": [
            {"id": t.id, "name": t.name, "zone_name": t.zone_name, **_current(row, now)}
            for t, row in rows
        ]
    }


async def _timeline(session, thermostat, start: datetime, end: datetime, step_s: int) -> list[dict]:
    readings = await session.execute(
        text(
            """
            SELECT time_bucket(:step * INTERVAL '1 second', time) AS bucket,
                   avg(ambient_c) AS ambient_c, avg(heat_c) AS heat_c, avg(cool_c) AS cool_c,
                   (array_agg(mode ORDER BY time DESC))[1] AS mode,
                   bool_or(hvac_status IN ('COOLING', 'HEATING')) AS running
            FROM thermostat_readings
            WHERE thermostat_id = :i AND time >= :start AND time < :end GROUP BY 1
            """
        ),
        {"step": step_s, "i": thermostat.id, "start": start, "end": end},
    )
    by_bucket = {r.bucket: r for r in readings}
    power: dict = {}
    if thermostat.zone_id is not None:
        rows = await session.execute(
            text(
                """
                SELECT b.bucket, sum(b.avg_w) * z.multiplier AS watts FROM zones z, LATERAL (
                    SELECT time_bucket(:step * INTERVAL '1 second', time) AS bucket, channel,
                           avg(power_w) AS avg_w
                    FROM channel_readings
                    WHERE channel = ANY(z.channels) AND time >= :start AND time < :end
                    GROUP BY 1, 2
                ) b WHERE z.id = :z GROUP BY 1, z.multiplier
                """
            ),
            {"step": step_s, "z": thermostat.zone_id, "start": start, "end": end},
        )
        power = {r.bucket: r.watts for r in rows}
    outdoor = await session.execute(
        text(
            """
            SELECT time_bucket(:step * INTERVAL '1 second', time) AS bucket, avg(temp_c) AS temp_c
            FROM outdoor_readings WHERE time >= :start AND time < :end GROUP BY 1
            """
        ),
        {"step": step_s, "start": start, "end": end},
    )
    outside = {r.bucket: r.temp_c for r in outdoor}

    timeline = []
    bucket = datetime.fromtimestamp(start.timestamp() // step_s * step_s, tz=start.tzinfo)
    while bucket < end:
        row = by_bucket.get(bucket)
        timeline.append(
            {
                "time": bucket,
                "ambient_f": _f(row.ambient_c) if row else None,
                "setpoint_f": _setpoint_f(row.mode, row.heat_c, row.cool_c) if row else None,
                "running": row.running if row else None,
                "ac_watts": power.get(bucket),
                "outdoor_f": _f(outside.get(bucket)),
            }
        )
        bucket += timedelta(seconds=step_s)
    return timeline


async def _on_peak_flag(session, thermostat, now: datetime) -> bool:
    if thermostat.zone_id is None or rate_period(now) != "on_peak":
        return False
    energy = await energy_by_zone(session, now - timedelta(hours=1), now)
    zone = next((e for e in energy if e.zone_id == thermostat.zone_id), None)
    return zone is not None and zone.kwh * 1000 >= ON_PEAK_FLAG_W


async def _estimate(session, thermostat, now: datetime) -> dict | None:
    if thermostat.zone_id is None:
        return None
    since = now - timedelta(days=ESTIMATE_DAYS)
    rows = await session.execute(
        text(
            """
            WITH days AS (
                SELECT time_bucket('1 day', time, 'America/New_York') AS day,
                       avg(cool_c) AS setpoint_c,
                       count(*) FILTER (WHERE hvac_status = 'COOLING') AS cooling,
                       count(*) FILTER (WHERE hvac_status = 'HEATING') AS heating
                FROM thermostat_readings WHERE thermostat_id = :i AND time >= :since GROUP BY 1
            ), outside AS (
                SELECT time_bucket('1 day', time, 'America/New_York') AS day, avg(temp_c) AS temp_c
                FROM outdoor_readings WHERE time >= :since GROUP BY 1
            ), power AS (
                SELECT h.bucket AS day, sum(h.avg_w * h.samples) * z.multiplier * :per_kwh AS kwh
                FROM zones z JOIN channel_daily h ON h.channel = ANY(z.channels)
                WHERE z.id = :z AND h.bucket >= :since GROUP BY 1, z.multiplier
            )
            SELECT d.day, p.kwh, o.temp_c, d.setpoint_c, d.cooling, d.heating
            FROM days d JOIN power p ON p.day = d.day LEFT JOIN outside o ON o.day = d.day
            """
        ),
        {
            "i": thermostat.id,
            "z": thermostat.zone_id,
            "since": since,
            "per_kwh": SAMPLE_INTERVAL_S / 3_600_000,
        },
    )
    days = [
        CoolingDay(
            r.day.astimezone(LOCAL).date(), r.kwh, r.temp_c, r.setpoint_c, r.cooling, r.heating
        )
        for r in rows
    ]
    energy = await energy_by_zone(session, since, now)
    zone = next((e for e in energy if e.zone_id == thermostat.zone_id), None)
    if zone is None or zone.kwh <= 0:
        return None
    estimate = cooling_estimate(days, cents_per_kwh=zone.est_cost / zone.kwh * 100)
    return vars(estimate) if estimate else None


@router.get("")
async def climate(request: Request, range: Range = "1d") -> dict:  # noqa: A002
    now: datetime = request.app.state.clock()
    span, step_s = _SPANS[range]
    async with request.app.state.sessions() as session:
        result = []
        for t in await list_paired(session):
            result.append(
                {
                    "id": t.id,
                    "name": t.name,
                    "zone_name": t.zone_name,
                    **_current(await _latest(session, t.id), now),
                    "timeline": await _timeline(session, t, now - span, now, step_s),
                    "on_peak_flag": await _on_peak_flag(session, t, now),
                    "estimate": await _estimate(session, t, now),
                }
            )
    return {"thermostats": result, "rate_period": rate_period(now)}


@router.post(
    "/{thermostat_id}/setpoint",
    dependencies=[Depends(require_action), Depends(require_pin)],
)
async def set_temperature(thermostat_id: int, body: SetpointIn, request: Request) -> dict:
    """The only path to a thermostat change: a person pressing a button, behind the PIN."""
    sdm = getattr(request.app.state, "sdm", None)
    if sdm is None:
        raise HTTPException(status_code=503, detail="Google is not set up")
    async with request.app.state.sessions() as session:
        device_id = await session.scalar(
            text("SELECT device_id FROM thermostats WHERE id = :i"), {"i": thermostat_id}
        )
    if device_id is None:
        raise HTTPException(status_code=404, detail="no such thermostat")
    try:
        # Ask Google for the state right now: the last recording can be a minute old.
        devices = await sdm.list_thermostats()
        device = next((d for d in devices if d.device_id == device_id), None)
        if device is None or not device.online:
            raise HTTPException(status_code=409, detail="That thermostat is offline.")
        if device.eco:
            raise HTTPException(
                status_code=409,
                detail="That thermostat is in Eco mode. Turn Eco off in the Google Home app.",
            )
        target_c = f_to_c(body.temp_f)
        if device.mode == "COOL":
            await sdm.set_setpoint(device_id, "COOL", cool_c=target_c)
        elif device.mode == "HEAT":
            await sdm.set_setpoint(device_id, "HEAT", heat_c=target_c)
        elif device.mode == "HEATCOOL":
            if body.target is None:
                raise HTTPException(status_code=422, detail="choose heat or cool")
            await sdm.set_setpoint(
                device_id,
                "HEATCOOL",
                cool_c=target_c if body.target == "cool" else device.cool_c,
                heat_c=target_c if body.target == "heat" else device.heat_c,
            )
        else:
            raise HTTPException(status_code=409, detail="That thermostat is off.")
    except RateLimited as exc:
        raise HTTPException(
            status_code=503, detail="Google asked us to slow down. Try again in a minute."
        ) from exc
    except NestError as exc:
        raise HTTPException(
            status_code=502, detail="Google did not accept that. Try again."
        ) from exc
    return {"ok": True}
