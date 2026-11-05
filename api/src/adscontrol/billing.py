"""What the current bill will be, against the last one.

The period starts the day after the latest bill ends and lasts as long as that bill did. Energy so
far is the whole house's counter energy plus hand-entered days; the rest of the period is projected
at the average daily use so far. Every figure here is an estimate and is shown as one.
"""

from datetime import date, datetime, time, timedelta
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from adscontrol.energy import energy_by_zone, manual_days, manual_share
from adscontrol.rates import LOCAL, all_in_cents, list_rates, version_in_force

ABOUT_THE_SAME = 0.03
MIN_DAYS_TO_PROJECT = 1.0


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=LOCAL)


def _verdict(change: float) -> Literal["less", "more", "about the same"]:
    if abs(change) <= ABOUT_THE_SAME:
        return "about the same"
    return "less" if change < 0 else "more"


async def current_bill(session: AsyncSession, now: datetime) -> dict | None:
    last = (
        await session.execute(
            text(
                "SELECT period_start, period_end, on_peak_kwh, off_peak_kwh, super_off_peak_kwh, "
                "actual_charge FROM bills ORDER BY period_end DESC LIMIT 1"
            )
        )
    ).first()
    if last is None:
        return None
    start = last.period_end + timedelta(days=1)
    days = (last.period_end - last.period_start).days + 1
    end = start + timedelta(days=days - 1)
    today = now.astimezone(LOCAL).date()
    day = min(max((today - start).days + 1, 0), days)

    measured_until = min(now, _midnight(end + timedelta(days=1)))
    zone_id = await session.scalar(text("SELECT id FROM zones WHERE kind = 'incoming'"))
    whole = next(
        e
        for e in await energy_by_zone(session, _midnight(start), measured_until)
        if e.zone_id == zone_id
    )
    manual = await manual_days(session, start, min(today, end))
    rate = version_in_force(await list_rates(session), today)

    # Hand-entered days have no time of day: price them with this period's measured day/night mix,
    # or the last bill's when nothing is measured yet.
    if whole.kwh > 0:
        split = {p: kwh / whole.kwh for p, kwh in whole.by_period.items()}
    else:
        billed = {
            "on_peak": last.on_peak_kwh or 0,
            "off_peak": last.off_peak_kwh or 0,
            "super_off_peak": last.super_off_peak_kwh or 0,
        }
        total = sum(billed.values())
        split = (
            {p: kwh / total for p, kwh in billed.items()}
            if total
            else {"off_peak": 0.5, "super_off_peak": 0.5}
        )
    manual_cents = sum(share * all_in_cents(rate, period) for period, share in split.items())
    manual_kwh, manual_covered_days = manual_share(manual, _midnight(start), measured_until)

    kwh_so_far = whole.kwh + manual_kwh
    energy_cost = whole.est_cost + manual_kwh * manual_cents / 100
    basic_day = rate.basic_per_day * rate.adder_factor  # the bill's percentage charges apply to it
    # Project from the time that has data, not the time elapsed: an outage would otherwise read as
    # low use, and a few hours into a period are too little to scale up to a month.
    measured_days = whole.coverage * (measured_until - _midnight(start)).total_seconds() / 86400
    covered_days = manual_covered_days + measured_days
    projected_kwh = projected_cost = change = None
    if covered_days >= MIN_DAYS_TO_PROJECT and kwh_so_far > 0:
        projected_kwh = kwh_so_far / covered_days * days
        projected_cost = projected_kwh * energy_cost / kwh_so_far + basic_day * days
        if last.actual_charge:
            change = (projected_cost - last.actual_charge) / last.actual_charge
    return {
        "period_start": start,
        "period_end": end,
        "day": day,
        "days": days,
        "kwh_so_far": kwh_so_far,
        "cost_so_far": energy_cost + basic_day * day,
        "projected_kwh": projected_kwh,
        "projected_cost": projected_cost,
        "last_charge": last.actual_charge,
        "change_pct": change,
        "verdict": None if change is None else _verdict(change),
        "manual_days": len(manual),
    }
