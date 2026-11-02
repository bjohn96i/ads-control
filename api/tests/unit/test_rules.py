from datetime import date, datetime, timedelta, timezone

from adscontrol.detect.rules import (
    HourSample,
    anomaly_finding,
    creep_finding,
    days_with_data,
    is_anomaly,
    is_creep,
)
from adscontrol.rates import LOCAL

NOW = datetime(2026, 10, 21, 8, 30, tzinfo=timezone.utc)  # 4:30 AM Eastern, a Wednesday
LAST = NOW.replace(minute=0)


def history(days: int, watts: float = 20.0, *, start: datetime = LAST) -> list[HourSample]:
    return [HourSample(start - timedelta(hours=h), watts) for h in range(3, days * 24)]


def spike(watts: float, hours: int = 2) -> list[HourSample]:
    return [HourSample(LAST - timedelta(hours=h), watts) for h in range(1, hours + 1)]


def test_office_at_600w_at_3am_is_anomaly():
    assert anomaly_finding(history(21) + spike(600.0), NOW) is not None


def test_finding_explains_itself():
    finding = anomaly_finding(history(21) + spike(600.0), NOW)
    assert "600 W" in finding.summary
    assert "20 W" in finding.summary


def test_normal_variation_is_not_anomaly():
    assert anomaly_finding(history(21) + spike(40.0), NOW) is None


def test_100_watt_floor_applies_when_the_baseline_is_flat():
    assert is_anomaly(119.0, 20.0, 0.0) is False
    assert is_anomaly(121.0, 20.0, 0.0) is True


def test_spread_widens_the_threshold():
    assert is_anomaly(300.0, 100.0, 60.0) is False
    assert is_anomaly(400.0, 100.0, 60.0) is True


def test_one_hour_spike_does_not_fire():
    samples = history(21) + [
        HourSample(LAST - timedelta(hours=1), 600.0),
        HourSample(LAST - timedelta(hours=2), 20.0),
    ]
    assert anomaly_finding(samples, NOW) is None


def test_zone_still_learning_never_flags():
    assert anomaly_finding(history(10) + spike(600.0), NOW) is None


def test_gap_days_do_not_count_toward_learning():
    # 21 calendar days back, but only every other local day holds data.
    samples = [s for s in history(21) if s.hour.astimezone(LOCAL).toordinal() % 2 == 0] + spike(
        600.0
    )
    assert days_with_data(samples) < 14
    assert anomaly_finding(samples, NOW) is None


def test_missing_recent_hour_does_not_fire():
    samples = history(21) + [HourSample(LAST - timedelta(hours=1), 600.0)]
    assert anomaly_finding(samples, NOW) is None


def test_weekend_is_judged_against_weekends():
    # Busy every weekend afternoon, quiet on weekdays. Saturday's load is normal.
    saturday = datetime(2026, 10, 24, 19, 30, tzinfo=timezone.utc)  # 3:30 PM Eastern
    last = saturday.replace(minute=0)
    samples = []
    for h in range(3, 28 * 24):
        hour = last - timedelta(hours=h)
        local_weekend = hour.astimezone(timezone(timedelta(hours=-4))).weekday() >= 5
        samples.append(HourSample(hour, 800.0 if local_weekend else 20.0))
    samples += [
        HourSample(last - timedelta(hours=1), 800.0),
        HourSample(last - timedelta(hours=2), 800.0),
    ]
    assert anomaly_finding(samples, saturday) is None


def days(n: int, kwh: float, end: date) -> dict[date, float]:
    return {end - timedelta(days=i): kwh for i in range(n)}


END = date(2026, 10, 20)


def test_is_creep_needs_ratio_and_size():
    assert is_creep([2.0] * 14, [1.0] * 28) is True
    assert is_creep([1.1] * 14, [1.0] * 28) is False  # under 25%
    assert is_creep([0.3] * 14, [0.1] * 28) is False  # big ratio, tiny energy


def test_fridge_drift_is_creep():
    daily = {**days(49, 1.0, END), **days(21, 2.0, END)}
    finding = creep_finding(daily, seasonal=False)
    assert finding is not None
    assert "1.0" in finding.summary and "2.0" in finding.summary


def test_ac_summer_rise_is_not_creep():
    daily = {**days(49, 1.0, END), **days(21, 20.0, END)}
    assert creep_finding(daily, seasonal=True) is None


def test_short_rise_is_not_creep():
    # Only the last 3 days are high: not sustained for a week.
    daily = {**days(49, 1.0, END), **days(3, 9.0, END)}
    assert creep_finding(daily, seasonal=False) is None


def test_too_little_history_is_not_creep():
    assert creep_finding(days(20, 5.0, END), seasonal=False) is None
