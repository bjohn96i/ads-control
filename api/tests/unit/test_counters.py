from datetime import datetime, timedelta, timezone

from adscontrol.counters import hourly_from_counter

H = datetime(2026, 11, 4, 10, tzinfo=timezone.utc)


def test_contiguous_readings_sum_into_their_hour():
    points = [(H + timedelta(seconds=10 * i), 1000 + i) for i in range(361)]  # 1 Wh per 10 s
    out = hourly_from_counter(points)
    assert out[H] == (359.0, False)
    assert out[H + timedelta(hours=1)] == (1.0, False)


def test_a_drop_is_the_monthly_reset_not_negative_energy():
    points = [(H, 980_000), (H + timedelta(seconds=10), 980_005), (H + timedelta(seconds=20), 3)]
    assert hourly_from_counter(points)[H] == (8.0, False)  # 5 before the reset, 3 after


def test_a_gap_is_spread_over_the_hours_it_spans():
    points = [(H + timedelta(minutes=30), 0), (H + timedelta(hours=2, minutes=30), 600)]
    out = hourly_from_counter(points)
    assert out[H] == (150.0, True)
    assert out[H + timedelta(hours=1)] == (300.0, True)
    assert out[H + timedelta(hours=2)] == (150.0, True)


def test_a_reset_inside_a_gap_counts_only_what_came_after():
    points = [(H, 990_000), (H + timedelta(hours=2), 400)]
    assert sum(wh for wh, _ in hourly_from_counter(points).values()) == 400.0


def test_a_bogus_low_reading_cant_put_a_month_into_one_hour():
    """A transient 0 then back to the real total: the climb back is capped at what a circuit can
    physically draw in that time (48 kW), not counted as a month of energy."""
    points = [(H, 980_000), (H + timedelta(seconds=10), 0), (H + timedelta(seconds=20), 980_010)]
    wh, _ = hourly_from_counter(points)[H]
    assert wh <= 48_000 * 20 / 3600
