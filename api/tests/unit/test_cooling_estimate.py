from datetime import date, timedelta

import pytest

from adscontrol.climate import (
    MIN_COOLING_DAYS,
    CoolingDay,
    c_to_f,
    cooling_estimate,
    f_to_c,
)


def days(n: int, *, heating: float = 0.0, cooling: float = 300.0) -> list[CoolingDay]:
    start = date(2026, 7, 1)
    return [
        # Each extra degree between outside and the setpoint costs exactly 2 kWh a day.
        CoolingDay(
            day=start + timedelta(days=i),
            kwh=4 + 2 * (i % 10),
            outdoor_c=25 + (i % 10),
            setpoint_c=25.0,
            cooling_minutes=cooling,
            heating_minutes=heating,
        )
        for i in range(n)
    ]


def test_f_to_c_conversion():
    assert f_to_c(72) == pytest.approx(22.2222, abs=0.001)
    assert f_to_c(32) == 0
    assert c_to_f(19.444445) == pytest.approx(67.0, abs=0.01)


def test_no_estimate_before_21_cooling_days():
    assert MIN_COOLING_DAYS == 21
    assert cooling_estimate(days(20), cents_per_kwh=20) is None


def test_estimate_from_enough_days():
    estimate = cooling_estimate(days(21), cents_per_kwh=20)
    assert estimate.kwh_per_degree_day == pytest.approx(2.0)
    # 2 kWh a day, 30 days, 20 cents, per Celsius degree; a Fahrenheit degree is 5/9 of that.
    assert estimate.dollars_per_f_degree_month == pytest.approx(2 * 30 * 0.2 * 5 / 9)
    assert estimate.days == 21
    assert estimate.full_season is False


def test_a_full_season_is_reported():
    assert cooling_estimate(days(90), cents_per_kwh=20).full_season is True


def test_heating_days_excluded_from_estimate():
    assert cooling_estimate(days(40, heating=60), cents_per_kwh=20) is None


def test_days_without_cooling_are_excluded():
    assert cooling_estimate(days(40, cooling=0), cents_per_kwh=20) is None


def test_no_weather_variation_gives_no_estimate():
    flat = [
        CoolingDay(date(2026, 7, 1) + timedelta(days=i), 5.0, 30.0, 25.0, 300.0, 0.0)
        for i in range(30)
    ]
    assert cooling_estimate(flat, cents_per_kwh=20) is None


def test_nonsense_slope_gives_no_estimate():
    backwards = [
        CoolingDay(date(2026, 7, 1) + timedelta(days=i), 30.0 - i, 25.0 + i * 0.3, 25.0, 300.0, 0.0)
        for i in range(30)
    ]
    assert cooling_estimate(backwards, cents_per_kwh=20) is None


def test_missing_values_are_skipped():
    day = CoolingDay(date(2026, 7, 1), 5.0, None, 25.0, 300.0, 0.0)
    assert cooling_estimate([day] * 40, cents_per_kwh=20) is None
