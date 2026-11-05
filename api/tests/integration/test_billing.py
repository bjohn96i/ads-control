from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import text

from adscontrol.billing import current_bill
from adscontrol.energy import add_manual_day
from adscontrol.rates import LOCAL, SEED_RATE, all_in_cents

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 4, 18, 0, tzinfo=LOCAL)
PERIOD_START = datetime(2026, 10, 24, tzinfo=LOCAL)
JOHNS_DAYS = {
    date(2026, 10, 24): 24.714,
    date(2026, 10, 25): 34.391,
    date(2026, 10, 26): 24.868,
    date(2026, 10, 27): 23.651,
    date(2026, 10, 28): 40.057,
    date(2026, 10, 29): 27.309,
    date(2026, 10, 30): 24.183,
    date(2026, 10, 31): 26.581,
    date(2026, 11, 1): 26.090,
}
HOURS = 66  # Nov 2 00:00 to Nov 4 18:00 local
SUPER_HOURS = 23  # of those, the ones from 23:00 to 07:00
BASIC_DAY = SEED_RATE.basic_per_day * SEED_RATE.adder_factor
SUPER_C = all_in_cents(SEED_RATE, "super_off_peak")
OFF_C = all_in_cents(SEED_RATE, "off_peak")


@pytest.fixture
async def period(session):
    await session.execute(text("TRUNCATE bills, channel_energy, manual_daily_energy"))
    await session.execute(text("UPDATE zones SET multiplier = 1 WHERE kind = 'incoming'"))
    await session.commit()
    yield
    await session.execute(text("TRUNCATE bills, channel_energy, manual_daily_energy"))
    await session.commit()


async def _bill(session, charge: float = 150.26) -> None:
    await session.execute(
        text(
            "INSERT INTO bills (period_start, period_end, on_peak_kwh, off_peak_kwh, "
            "super_off_peak_kwh, total_kwh, actual_charge) "
            "VALUES ('2026-09-24', '2026-10-23', 30, 483, 546, 1058, :c)"
        ),
        {"c": charge},
    )
    await session.commit()


async def _johns_days(session) -> None:
    for day, kwh in JOHNS_DAYS.items():
        await add_manual_day(session, day, kwh)
    await session.commit()


async def _counter_days(session, total_kwh: float = 150.0, hours: int = HOURS) -> None:
    """Whole-house counter energy, even across the first `hours` of the 66 (channel 1; 7 is 0)."""
    start = datetime(2026, 11, 2, tzinfo=LOCAL)
    for i in range(hours):
        hour = start + timedelta(hours=i)
        await session.execute(
            text(
                "INSERT INTO channel_energy VALUES (:h, 1, :wh, 'counter'), (:h, 7, 0, 'counter')"
            ),
            {"h": hour, "wh": total_kwh * 1000 / hours},
        )
    await session.commit()


def _expected(manual_kwh: float, counter_kwh: float) -> tuple[float, float]:
    counter_cost = (
        counter_kwh / HOURS * (SUPER_HOURS * SUPER_C + (HOURS - SUPER_HOURS) * OFF_C) / 100
    )
    manual_cents = SUPER_HOURS / HOURS * SUPER_C + (HOURS - SUPER_HOURS) / HOURS * OFF_C
    return manual_kwh + counter_kwh, counter_cost + manual_kwh * manual_cents / 100


async def test_period_follows_the_last_bill(session, period):
    await _bill(session)
    bill = await current_bill(session, NOW)
    assert (bill["period_start"], bill["period_end"]) == (date(2026, 10, 24), date(2026, 11, 22))
    assert (bill["day"], bill["days"]) == (12, 30)


async def test_so_far_adds_counter_energy_and_hand_entered_days(session, period):
    await _bill(session)
    await _johns_days(session)
    await _counter_days(session)
    bill = await current_bill(session, NOW)
    kwh, energy_cost = _expected(sum(JOHNS_DAYS.values()), 150.0)
    assert bill["kwh_so_far"] == pytest.approx(kwh)
    assert bill["manual_days"] == 9
    assert bill["cost_so_far"] == pytest.approx(energy_cost + 12 * BASIC_DAY)


async def test_projection_scales_by_days_and_adds_basic_for_the_whole_period(session, period):
    await _bill(session)
    await _johns_days(session)
    await _counter_days(session)
    bill = await current_bill(session, NOW)
    kwh, energy_cost = _expected(sum(JOHNS_DAYS.values()), 150.0)
    covered = 9 + HOURS / 24  # days with data: the nine hand-entered ones and 66 recorded hours
    assert bill["projected_kwh"] == pytest.approx(kwh / covered * 30)
    assert bill["projected_cost"] == pytest.approx(
        kwh / covered * 30 * energy_cost / kwh + 30 * BASIC_DAY
    )


async def test_an_outage_doesnt_drag_the_projection_down(session, period):
    """Recording stopped after 33 of the 66 hours: project from the time that has data."""
    await _bill(session)
    await _johns_days(session)
    await _counter_days(session, total_kwh=75.0, hours=33)
    bill = await current_bill(session, NOW)
    assert bill["projected_kwh"] == pytest.approx(
        (sum(JOHNS_DAYS.values()) + 75) / (9 + 33 / 24) * 30
    )


async def test_less_than_a_day_of_data_gives_no_projection(session, period):
    await _bill(session)
    await _counter_days(session, total_kwh=6.0, hours=6)
    bill = await current_bill(session, NOW)
    assert bill["kwh_so_far"] == pytest.approx(6.0)
    assert (bill["projected_kwh"], bill["projected_cost"], bill["verdict"]) == (None, None, None)


async def test_verdict_uses_three_percent(session, period):
    await _bill(session)
    await _johns_days(session)
    await _counter_days(session)
    projected = (await current_bill(session, NOW))["projected_cost"]
    await session.execute(text("UPDATE bills SET actual_charge = :c"), {"c": projected * 1.02})
    await session.commit()
    assert (await current_bill(session, NOW))["verdict"] == "about the same"
    await session.execute(text("UPDATE bills SET actual_charge = :c"), {"c": projected * 1.5})
    await session.commit()
    bill = await current_bill(session, NOW)
    assert bill["verdict"] == "less"
    assert bill["change_pct"] == pytest.approx(1 / 1.5 - 1)
    assert bill["last_charge"] == pytest.approx(projected * 1.5)


async def test_no_counter_days_falls_back_to_the_last_bills_split(session, period):
    await _bill(session)
    await _johns_days(session)
    bill = await current_bill(session, NOW)
    manual = sum(JOHNS_DAYS.values())
    # The bill's periods add to 1,059 kWh though its total says 1,058; the shares use the parts.
    bill_cents = (30 * all_in_cents(SEED_RATE, "on_peak") + 483 * OFF_C + 546 * SUPER_C) / 1059
    assert bill["cost_so_far"] == pytest.approx(manual * bill_cents / 100 + 12 * BASIC_DAY)


async def test_no_energy_yet_returns_a_zero_projection_without_dividing_by_zero(session, period):
    await _bill(session)
    bill = await current_bill(session, NOW)
    assert bill["kwh_so_far"] == 0
    assert (bill["projected_kwh"], bill["projected_cost"], bill["change_pct"]) == (None, None, None)


async def test_no_bill_means_no_estimate(session, period):
    assert await current_bill(session, NOW) is None
