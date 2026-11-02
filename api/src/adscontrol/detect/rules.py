"""Is a zone doing something unusual? Pure decisions over values the store narrows in SQL."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from statistics import median

from adscontrol.rates import LOCAL

LEARNING_DAYS = 14
BASELINE_DAYS = 28
ANOMALY_HOURS = 2
ANOMALY_MADS = 4
ANOMALY_FLOOR_W = 100.0
CREEP_RATIO = 1.25
CREEP_MIN_KWH = 0.5
CREEP_RECENT_DAYS = 14
CREEP_PRIOR_DAYS = 28
CREEP_SUSTAINED_DAYS = 7


@dataclass(frozen=True)
class HourSample:
    hour: datetime
    watts: float


@dataclass(frozen=True)
class Finding:
    kind: str
    summary: str
    evidence: dict = field(default_factory=dict)


def _slot(hour: datetime) -> tuple[int, bool]:
    local = hour.astimezone(LOCAL)
    return local.hour, local.weekday() >= 5


def days_with_data(samples: list[HourSample]) -> int:
    return len({s.hour.astimezone(LOCAL).date() for s in samples})


def is_anomaly(watts: float, baseline_median: float, baseline_mad: float) -> bool:
    return watts > max(
        baseline_median + ANOMALY_MADS * baseline_mad, baseline_median + ANOMALY_FLOOR_W
    )


def anomaly_finding(samples: list[HourSample], now: datetime) -> Finding | None:
    last = now.replace(minute=0, second=0, microsecond=0)
    recent_hours = [last - timedelta(hours=h) for h in range(1, ANOMALY_HOURS + 1)]
    recent = {s.hour: s.watts for s in samples if s.hour in recent_hours}
    if len(recent) < ANOMALY_HOURS:
        return None
    since = last - timedelta(days=BASELINE_DAYS)
    baseline = [s for s in samples if since <= s.hour < recent_hours[-1]]
    if days_with_data(baseline) < LEARNING_DAYS:
        return None

    medians = []
    for hour, watts in recent.items():
        same_slot = [s.watts for s in baseline if _slot(s.hour) == _slot(hour)]
        if not same_slot:
            return None
        center = median(same_slot)
        mad = median(abs(w - center) for w in same_slot)
        if not is_anomaly(watts, center, mad):
            return None
        medians.append(center)

    watts = max(recent.values())
    usual = max(medians)
    return Finding(
        "anomaly",
        f"Unusually high: {watts:.0f} W this hour, usually about {usual:.0f} W",
        {"watts": watts, "usual_w": usual},
    )


def is_creep(recent_daily_kwh: list[float], prior_daily_kwh: list[float]) -> bool:
    recent, prior = median(recent_daily_kwh), median(prior_daily_kwh)
    return recent >= prior * CREEP_RATIO and recent - prior >= CREEP_MIN_KWH


def creep_finding(daily_kwh: dict[date, float], *, seasonal: bool) -> Finding | None:
    # An A/C rising with the weather is the season, not a fault.
    if seasonal or not daily_kwh:
        return None
    latest = max(daily_kwh)
    recent = prior = None
    for back in range(CREEP_SUSTAINED_DAYS):
        end = latest - timedelta(days=back)
        window = [end - timedelta(days=i) for i in range(CREEP_RECENT_DAYS + CREEP_PRIOR_DAYS)]
        recent = [daily_kwh[d] for d in window[:CREEP_RECENT_DAYS] if d in daily_kwh]
        prior = [daily_kwh[d] for d in window[CREEP_RECENT_DAYS:] if d in daily_kwh]
        # Most days must exist on both sides, or the comparison means little.
        if len(recent) < CREEP_RECENT_DAYS * 0.7 or len(prior) < CREEP_PRIOR_DAYS * 0.7:
            return None
        if not is_creep(recent, prior):
            return None
    was, now_ = median(prior), median(recent)
    return Finding(
        "creep",
        f"Typical use has risen from {was:.1f} to {now_:.1f} kWh a day",
        {"prior_kwh": was, "recent_kwh": now_},
    )
