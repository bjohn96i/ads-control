"""Georgia Power Overnight Advantage (TOU-OA-14) time-of-use periods and dated prices.

Prices are per kWh with the fuel rider (TOU-FCR-TP-5, secondary) included. adder_factor carries
the percentage charges on a bill; they were derived from the October 2026 bill.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

LOCAL = ZoneInfo("America/New_York")
RatePeriod = Literal["on_peak", "off_peak", "super_off_peak"]


@dataclass(frozen=True)
class RateVersion:
    effective_from: date
    on_peak_c: float
    off_peak_c: float
    super_off_peak_c: float
    basic_per_day: float
    adder_factor: float
    source: str


SEED_RATE = RateVersion(
    effective_from=date(2026, 6, 1),
    on_peak_c=35.0137,
    off_peak_c=14.0366,
    super_off_peak_c=5.6606,
    basic_per_day=0.4603,
    adder_factor=1.1882,
    source="TOU-OA-14 (Jan 2025) + TOU-FCR-TP-5 (Jun 2026), adders from the Oct 2026 bill",
)


def _observed(day: date) -> date:
    """A holiday on Saturday is observed Friday; on Sunday, Monday."""
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _is_on_peak_holiday(day: date) -> bool:
    independence = _observed(date(day.year, 7, 4))
    first_sept = date(day.year, 9, 1)
    labor = first_sept + timedelta(days=(7 - first_sept.weekday()) % 7)
    return day in (independence, labor)


def rate_period(t: datetime) -> RatePeriod:
    if t.tzinfo is None:
        raise ValueError("rate_period needs a timezone-aware datetime")
    local = t.astimezone(LOCAL)
    if local.hour >= 23 or local.hour < 7:
        return "super_off_peak"
    if (
        6 <= local.month <= 9
        and local.weekday() < 5
        and 14 <= local.hour < 19
        and not _is_on_peak_holiday(local.date())
    ):
        return "on_peak"
    return "off_peak"


def all_in_cents(rate: RateVersion, period: RatePeriod) -> float:
    return getattr(rate, f"{period}_c") * rate.adder_factor


def version_in_force(versions: list[RateVersion], day: date) -> RateVersion:
    ordered = sorted(versions, key=lambda v: v.effective_from)
    in_force = [v for v in ordered if v.effective_from <= day]
    return in_force[-1] if in_force else ordered[0]


async def list_rates(session: AsyncSession) -> list[RateVersion]:
    rows = await session.execute(
        text(
            "SELECT effective_from, on_peak_c, off_peak_c, super_off_peak_c, basic_per_day, adder_factor, source FROM rate_versions"
        )
    )
    return [RateVersion(**row._mapping) for row in rows]


async def rate_for(session: AsyncSession, day: date) -> RateVersion:
    return version_in_force(await list_rates(session), day)
