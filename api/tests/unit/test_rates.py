from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from adscontrol.rates import SEED_RATE, all_in_cents, rate_period, version_in_force

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
JULY_WEEKDAY = (2026, 7, 15)  # a Wednesday


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (6, 59, "super_off_peak"),
        (7, 0, "off_peak"),
        (13, 59, "off_peak"),
        (14, 0, "on_peak"),
        (18, 59, "on_peak"),
        (19, 0, "off_peak"),
        (22, 59, "off_peak"),
        (23, 0, "super_off_peak"),
    ],
)
def test_july_weekday_boundaries(hour, minute, expected):
    assert rate_period(datetime(*JULY_WEEKDAY, hour, minute, tzinfo=ET)) == expected


@pytest.mark.parametrize(
    "when",
    [
        datetime(2026, 7, 18, 15, tzinfo=ET),  # Saturday
        datetime(2026, 10, 14, 15, tzinfo=ET),  # October
        datetime(2026, 5, 29, 15, tzinfo=ET),  # the last Friday before summer
        datetime(2026, 9, 7, 15, tzinfo=ET),  # Labor Day
        datetime(2027, 7, 5, 15, tzinfo=ET),  # July 4 observed on Monday
        datetime(2026, 7, 3, 15, tzinfo=ET),  # July 4 2026 is a Saturday, observed Friday
    ],
)
def test_afternoon_that_is_not_on_peak(when):
    assert rate_period(when) == "off_peak"


def test_september_weekday_afternoon_is_on_peak():
    assert rate_period(datetime(2026, 9, 30, 15, tzinfo=ET)) == "on_peak"


def test_utc_input_is_judged_in_local_time():
    # 18:30 UTC in July is 2:30 PM Eastern.
    assert rate_period(datetime(*JULY_WEEKDAY, 18, 30, tzinfo=UTC)) == "on_peak"


@pytest.mark.parametrize("day", [date(2026, 11, 1), date(2027, 3, 14)])
def test_dst_days(day):
    """Every UTC hour of a clock-change day follows the local wall clock."""
    t = datetime(day.year, day.month, day.day, 12, tzinfo=UTC)
    for _ in range(48):
        local = t.astimezone(ET)
        expected = "super_off_peak" if local.hour >= 23 or local.hour < 7 else "off_peak"
        assert rate_period(t) == expected
        t += timedelta(hours=1)


def test_fall_back_day_has_two_1_am_hours_both_super_off_peak():
    assert rate_period(datetime(2026, 11, 1, 5, 30, tzinfo=UTC)) == "super_off_peak"
    assert rate_period(datetime(2026, 11, 1, 6, 30, tzinfo=UTC)) == "super_off_peak"


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        rate_period(datetime(2026, 7, 15, 15))


def test_reconciles_with_october_bill():
    r = SEED_RATE
    energy_c = 30 * r.on_peak_c + 483 * r.off_peak_c + 546 * r.super_off_peak_c
    total = (energy_c / 100 + 30 * r.basic_per_day) * r.adder_factor
    assert total == pytest.approx(150.26, rel=0.03)


def test_all_in_cents_includes_adders():
    assert all_in_cents(SEED_RATE, "on_peak") == pytest.approx(41.6, abs=0.05)
    assert all_in_cents(SEED_RATE, "super_off_peak") == pytest.approx(6.73, abs=0.05)


def test_rate_for_uses_version_in_force_on_that_day():
    old = SEED_RATE
    new = type(SEED_RATE)(
        **{**SEED_RATE.__dict__, "effective_from": date(2027, 1, 1), "on_peak_c": 40.0}
    )
    assert version_in_force([old, new], date(2026, 12, 31)) is old
    assert version_in_force([old, new], date(2027, 1, 1)) is new
    assert version_in_force([new, old], date(2027, 6, 1)) is new


def test_day_before_any_version_uses_the_earliest():
    assert version_in_force([SEED_RATE], date(2020, 1, 1)) is SEED_RATE
