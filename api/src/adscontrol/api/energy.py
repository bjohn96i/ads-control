"""Where the power goes: zones ranked by energy and estimated cost, and one zone's detail."""

from datetime import datetime, time, timedelta
from statistics import median
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from adscontrol.detect.store import open_findings
from adscontrol.energy import charger_estimate, energy_by_zone
from adscontrol.rates import LOCAL

router = APIRouter(prefix="/api/energy")
Range = Literal["bill", "7d", "30d"]


async def _span(request: Request, session, range_: str) -> tuple[datetime, datetime]:
    now: datetime = request.app.state.clock()
    if range_ == "bill":
        last_end = await session.scalar(text("SELECT max(period_end) FROM bills"))
        if last_end is not None:
            start = datetime.combine(last_end + timedelta(days=1), time.min, tzinfo=LOCAL)
            if start < now:
                return start, now
    days = 7 if range_ == "7d" else 30
    # Whole hours, so the rollups' first bucket is not a partial one.
    start = (now - timedelta(days=days)).replace(minute=0, second=0, microsecond=0)
    return start, now


def _line(kwh: float, cost: float, coverage: float, total: float) -> dict:
    return {
        "kwh": kwh,
        "est_cost": cost,
        "coverage": coverage,
        "share": kwh / total if total > 0 else 0,
    }


@router.get("/ranking")
async def ranking(request: Request, range: Range = "bill") -> dict:  # noqa: A002
    async with request.app.state.sessions() as session:
        start, end = await _span(request, session, range)
        energy = await energy_by_zone(session, start, end)
        charger_kwh, charger_cost = await charger_estimate(session, start, end)
        zones = {
            r.id: r for r in (await session.execute(text("SELECT id, kind, room FROM zones"))).all()
        }
    circuits = [e for e in energy if zones[e.zone_id].kind == "circuit"]
    whole = next(e for e in energy if zones[e.zone_id].kind == "incoming")
    # A multiplier or clamp noise can push the zones past the mains; that is not negative energy.
    explained_kwh = sum(e.kwh for e in circuits) + charger_kwh
    explained_cost = sum(e.est_cost for e in circuits) + charger_cost
    return {
        "start": start,
        "end": end,
        "zones": [
            {
                "id": e.zone_id,
                "name": e.name,
                "room": zones[e.zone_id].room,
                **_line(e.kwh, e.est_cost, e.coverage, whole.kwh),
            }
            for e in sorted(circuits, key=lambda e: e.kwh, reverse=True)
        ],
        "charger_estimate": _line(charger_kwh, charger_cost, whole.coverage, whole.kwh),
        "unmetered": _line(
            max(0.0, whole.kwh - explained_kwh),
            max(0.0, whole.est_cost - explained_cost),
            whole.coverage,
            whole.kwh,
        ),
        "whole_house": {
            "id": whole.zone_id,
            **_line(whole.kwh, whole.est_cost, whole.coverage, whole.kwh),
        },
    }


_ZONES = "SELECT id, name, channels, multiplier FROM zones WHERE "


@router.get("/zones/{zone_id}")
async def zone_detail(zone_id: int, request: Request, range: Range = "bill") -> dict:  # noqa: A002
    return await _detail(request, range, _ZONES + "id = :k", zone_id)


@router.get("/rooms/{room}")
async def room_detail(room: str, request: Request, range: Range = "bill") -> dict:  # noqa: A002
    return await _detail(request, range, _ZONES + "room = :k AND kind = 'circuit'", room)


async def _detail(request: Request, range_: str, query: str, key: int | str) -> dict:
    """One zone, or a room's circuits added up; a room's hour counts only when every circuit has it."""
    async with request.app.state.sessions() as session:
        zones = (await session.execute(text(query), {"k": key})).all()
        if not zones:
            raise HTTPException(status_code=404, detail="no such zone")
        start, end = await _span(request, session, range_)
        findings = await open_findings(session)
        hours = []
        for zone in zones:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT bucket, sum(avg_w) AS watts, count(*) AS channels
                        FROM channel_hourly
                        WHERE channel = ANY(:channels) AND bucket >= :start AND bucket < :end
                        GROUP BY 1
                        """
                    ),
                    {"channels": zone.channels, "start": start, "end": end},
                )
            ).all()
            hours.append(
                {
                    r.bucket: r.watts * zone.multiplier
                    for r in rows
                    if r.channels == len(zone.channels)
                }
            )

    by_hour = {h: sum(z[h] for z in hours) for h in hours[0] if all(h in z for z in hours)}
    series = []
    hour = start
    while hour < end:
        series.append({"time": hour, "watts": by_hour.get(hour)})
        hour += timedelta(hours=1)

    nights: dict = {}
    for bucket, watts in by_hour.items():
        local = bucket.astimezone(LOCAL)
        if 1 <= local.hour < 5:
            nights[local.date()] = min(watts, nights.get(local.date(), watts))
    return {
        "id": zones[0].id if isinstance(key, int) else None,
        "name": zones[0].name if isinstance(key, int) else key,
        "series": series,
        "overnight_min_w": median(nights.values()) if nights else None,
        "flags": [f for zone in zones for f in findings.get(zone.id, [])],
    }
