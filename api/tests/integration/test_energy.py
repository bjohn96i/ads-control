from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from adscontrol.energy import energy_by_zone

pytestmark = pytest.mark.integration

START = datetime(2026, 10, 14, 4, 0, tzinfo=timezone.utc)
DISHWASHER = 3


async def _insert(session, start, end, *, channel=DISHWASHER, watts=1000.0, consume="5"):
    await session.execute(
        text(
            f"""
            INSERT INTO channel_readings
            SELECT t, :channel, :watts, 120, 1, 1, {consume}
            FROM generate_series(CAST(:start AS timestamptz), CAST(:end AS timestamptz) - INTERVAL '10 seconds', INTERVAL '10 seconds') AS t
            """
        ),
        dict(channel=channel, watts=watts, start=start, end=end),
    )
    await session.commit()


def _named(energy, name):
    return next(z for z in energy if z.name == name)


async def test_energy_for_full_hour_at_1000w_is_1_kwh(session):
    end = START + timedelta(hours=1)
    await _insert(session, START, end)
    zone = _named(await energy_by_zone(session, START, end), "Dishwasher")
    assert zone.kwh == pytest.approx(1.0)
    assert zone.coverage == pytest.approx(1.0)


async def test_eight_hour_gap_reports_coverage_not_low_usage(session):
    end = START + timedelta(hours=24)
    await _insert(session, START, START + timedelta(hours=16))
    zone = _named(await energy_by_zone(session, START, end), "Dishwasher")
    assert zone.coverage == pytest.approx(16 / 24, abs=0.001)
    assert zone.kwh == pytest.approx(16.0)


async def test_counter_reset_in_consume_wh_does_not_affect_energy(session):
    end = START + timedelta(hours=1)
    # Falls from 400 to 0 halfway, as a month rollover or reboot would.
    await _insert(
        session, START, end, consume="CASE WHEN t < '2026-10-14 04:30+00' THEN 400 ELSE 0 END"
    )
    zone = _named(await energy_by_zone(session, START, end), "Dishwasher")
    assert zone.kwh == pytest.approx(1.0)


async def test_long_range_uses_rollups_with_same_answer(session):
    end = START + timedelta(days=3)
    await _insert(session, START, end)
    zone = _named(await energy_by_zone(session, START, end), "Dishwasher")
    assert zone.kwh == pytest.approx(72.0)
    assert zone.coverage == pytest.approx(1.0)


async def test_multiplier_scales_energy(session):
    await session.execute(text("UPDATE zones SET multiplier = 2 WHERE name = 'Dishwasher'"))
    try:
        end = START + timedelta(hours=1)
        await _insert(session, START, end)
        assert _named(await energy_by_zone(session, START, end), "Dishwasher").kwh == pytest.approx(
            2.0
        )
    finally:
        await session.execute(text("UPDATE zones SET multiplier = 1 WHERE name = 'Dishwasher'"))
        await session.commit()


async def test_zone_with_no_data_has_zero_coverage(session):
    end = START + timedelta(hours=1)
    zone = _named(await energy_by_zone(session, START, end), "Washer")
    assert zone.kwh == 0
    assert zone.coverage == 0


async def test_two_channel_zone_coverage_is_the_worse_channel(session):
    end = START + timedelta(hours=1)
    await _insert(session, START, end, channel=5)
    zone = _named(await energy_by_zone(session, START, end), "Dryer")
    assert zone.coverage == 0


async def test_by_period_splits_kwh_at_local_boundaries(session):
    # 10 PM to midnight Eastern in October: one hour off-peak, one super off-peak.
    start = datetime(2026, 10, 15, 2, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=2)
    await _insert(session, start, end)
    zone = _named(await energy_by_zone(session, start, end), "Dishwasher")
    assert zone.by_period["off_peak"] == pytest.approx(1.0)
    assert zone.by_period["super_off_peak"] == pytest.approx(1.0)


async def test_rate_for_reads_seeded_version(session):
    from datetime import date

    from adscontrol.rates import rate_for

    rate = await rate_for(session, date(2026, 10, 1))
    assert rate.on_peak_c == pytest.approx(35.0137)
    assert rate.adder_factor == pytest.approx(1.1882)
