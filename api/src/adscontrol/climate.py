"""Temperature units, and what a degree of cooling seems to cost."""

from dataclasses import dataclass
from datetime import date
from statistics import StatisticsError, linear_regression

MIN_COOLING_DAYS = 21
FULL_SEASON_DAYS = 90
DAYS_PER_MONTH = 30


def f_to_c(f: float) -> float:
    return (f - 32) * 5 / 9


def c_to_f(c: float) -> float:
    return c * 9 / 5 + 32


@dataclass(frozen=True)
class CoolingDay:
    day: date
    kwh: float
    outdoor_c: float | None
    setpoint_c: float | None
    cooling_minutes: float
    heating_minutes: float


@dataclass(frozen=True)
class Estimate:
    kwh_per_degree_day: float
    dollars_per_f_degree_month: float
    days: int
    full_season: bool


def cooling_estimate(days: list[CoolingDay], cents_per_kwh: float) -> Estimate | None:
    """Fits daily A/C energy against how far outside sits above the setpoint.

    Lowering the setpoint by a degree widens that gap by a degree, so the slope is the cost of
    one degree. Heating days are left out: heat is gas, which this monitor cannot see.
    """
    usable = [
        d
        for d in days
        if d.cooling_minutes > 0
        and d.heating_minutes == 0
        and d.outdoor_c is not None
        and d.setpoint_c is not None
    ]
    if len(usable) < MIN_COOLING_DAYS:
        return None
    try:
        slope, _ = linear_regression(
            [d.outdoor_c - d.setpoint_c for d in usable], [d.kwh for d in usable]
        )
    except StatisticsError:  # every day had the same gap
        return None
    if slope <= 0:
        return None
    return Estimate(
        kwh_per_degree_day=slope,
        dollars_per_f_degree_month=slope * DAYS_PER_MONTH * cents_per_kwh / 100 * 5 / 9,
        days=len(usable),
        full_season=len(usable) >= FULL_SEASON_DAYS,
    )
