from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import text

from adscontrol.app import create_app
from adscontrol.config import Settings

pytestmark = pytest.mark.integration

NOW = datetime(2026, 7, 15, 18, 30, tzinfo=timezone.utc)  # 2:30 PM Eastern: on-peak


def _app(url):
    app = create_app(Settings(database_url=url), jobs=[], start_jobs=False)
    app.state.clock = lambda: NOW
    return app


async def _get(url) -> dict:
    transport = httpx.ASGITransport(app=_app(url))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        return (await client.get("/api/live")).json()


async def _sample(session, by_channel: dict[int, float], at: datetime = NOW):
    await session.execute(
        text("INSERT INTO channel_readings VALUES (:t, :c, :w, 120, 1, 1, 0)"),
        [{"t": at, "c": c, "w": w} for c, w in by_channel.items()],
    )
    await session.commit()


FULL = {c: 0.0 for c in range(1, 19)}


async def test_whole_house_is_a1_plus_b1(session, migrated_db):
    await _sample(session, {**FULL, 1: 1000.0, 7: 500.0})
    assert (await _get(migrated_db))["whole_house_w"] == pytest.approx(1500)


async def test_unmetered_is_whole_minus_zones(session, migrated_db):
    await _sample(session, {**FULL, 1: 1000.0, 7: 500.0, 3: 900.0, 5: 100.0, 11: 100.0})
    body = await _get(migrated_db)
    assert body["unmetered_w"] == pytest.approx(400)
    dryer = next(z for z in body["zones"] if z["name"] == "Dryer")
    assert dryer["watts"] == pytest.approx(200)


async def test_small_negative_unmetered_reports_zero(session, migrated_db):
    await _sample(session, {**FULL, 1: 100.0, 3: 130.0})
    assert (await _get(migrated_db))["unmetered_w"] == 0


async def test_stale_after_30s_returns_null_watts_not_zero(session, migrated_db):
    await _sample(session, {**FULL, 1: 1000.0}, NOW - timedelta(seconds=31))
    body = await _get(migrated_db)
    assert body["stale"] is True
    assert body["whole_house_w"] is None
    assert body["unmetered_w"] is None
    assert body["cost_per_hour_estimate"] is None
    assert all(z["watts"] is None for z in body["zones"])


async def test_fresh_at_29s(session, migrated_db):
    await _sample(session, {**FULL, 1: 1000.0}, NOW - timedelta(seconds=29))
    body = await _get(migrated_db)
    assert body["stale"] is False
    assert body["whole_house_w"] == pytest.approx(1000)


async def test_no_readings_ever_is_stale(session, migrated_db):
    body = await _get(migrated_db)
    assert body["stale"] is True
    assert body["as_of"] is None


async def test_whole_house_zone_is_not_listed_as_a_pin(session, migrated_db):
    await _sample(session, FULL)
    names = {z["name"] for z in (await _get(migrated_db))["zones"]}
    assert "Whole House" not in names
    assert len(names) == 12


async def test_cost_uses_current_rate_period(session, migrated_db):
    await _sample(session, {**FULL, 1: 1000.0})
    body = await _get(migrated_db)
    assert body["rate_period"] == "on_peak"
    assert body["cost_per_hour_estimate"] == pytest.approx(0.416, abs=0.001)


async def test_live_skips_month_totals_no_page_uses(session, migrated_db):
    # Recomputed every 5 s per open page; the home page shows today instead.
    await _sample(session, {**FULL, 1: 1000.0})
    body = await _get(migrated_db)
    assert "month_kwh" not in body and "month_coverage" not in body


async def _charging(session, seconds_ago: list[int], whole: float):
    for ago in seconds_ago:
        await _sample(session, {**FULL, 1: whole / 2, 7: whole / 2}, NOW - timedelta(seconds=ago))


async def test_sustained_unmetered_load_is_estimated_as_the_charger(session, migrated_db):
    await _charging(session, [20, 10, 0], 7200.0)
    charger = (await _get(migrated_db))["charger_estimate_w"]
    assert charger == pytest.approx(7200)


async def test_one_spike_is_not_the_charger(session, migrated_db):
    await _charging(session, [20, 10], 100.0)
    await _charging(session, [0], 7200.0)
    assert (await _get(migrated_db))["charger_estimate_w"] == 0


async def test_normal_background_is_not_the_charger(session, migrated_db):
    await _charging(session, [20, 10, 0], 300.0)
    assert (await _get(migrated_db))["charger_estimate_w"] == 0


async def test_load_on_a_zone_is_not_the_charger(session, migrated_db):
    for ago in (20, 10, 0):
        await _sample(session, {**FULL, 1: 4000.0, 7: 0.0, 3: 4000.0}, NOW - timedelta(seconds=ago))
    assert (await _get(migrated_db))["charger_estimate_w"] == 0


async def test_too_few_recent_readings_is_not_the_charger(session, migrated_db):
    await _charging(session, [0], 7200.0)
    assert (await _get(migrated_db))["charger_estimate_w"] == 0


async def test_stale_data_has_no_charger_estimate(session, migrated_db):
    await _charging(session, [60, 50, 40], 7200.0)
    assert (await _get(migrated_db))["charger_estimate_w"] is None


async def test_zones_carry_room_and_floor(session, migrated_db):
    await _sample(session, FULL)
    dryer = next(z for z in (await _get(migrated_db))["zones"] if z["name"] == "Dryer")
    assert (dryer["room"], dryer["floor"]) == ("Laundry", "Basement")


async def _outdoor(
    session, temp_c: float, at: datetime, code: int | None = None, day: bool | None = None
):
    await session.execute(text("TRUNCATE outdoor_readings"))
    await session.execute(
        text("INSERT INTO outdoor_readings VALUES (:t, :c, :w, :d)"),
        {"t": at, "c": temp_c, "w": code, "d": day},
    )
    await session.commit()


async def test_outdoor_temperature_in_fahrenheit(session, migrated_db):
    await _outdoor(session, 20.0, NOW - timedelta(hours=1))
    assert (await _get(migrated_db))["outdoor_f"] == pytest.approx(68)


async def test_old_outdoor_temperature_is_left_out(session, migrated_db):
    await _outdoor(session, 20.0, NOW - timedelta(hours=4), 61, True)
    body = await _get(migrated_db)
    assert body["outdoor_f"] is None
    assert body["outdoor_code"] is None
    assert body["outdoor_is_day"] is None


async def test_current_weather_comes_with_the_temperature(session, migrated_db):
    await _outdoor(session, 20.0, NOW - timedelta(hours=1), 3, False)
    body = await _get(migrated_db)
    assert (body["outdoor_code"], body["outdoor_is_day"]) == (3, False)


async def test_today_energy_counts_from_local_midnight(session, migrated_db):
    # 3 AM UTC is 11 PM Eastern the night before, so it isn't today.
    await _sample(session, {**FULL, 1: 2000.0}, datetime(2026, 7, 15, 3, 0, tzinfo=timezone.utc))
    before = await _get(migrated_db)
    assert before["today_kwh"] == 0
    await _sample(session, {**FULL, 1: 2000.0}, NOW - timedelta(minutes=10))
    after = await _get(migrated_db)
    assert after["today_kwh"] > 0
    assert after["today_cost"] > 0


async def test_recent_line_is_one_point_per_minute(session, migrated_db):
    await _sample(session, {**FULL, 1: 1000.0}, NOW - timedelta(seconds=90))
    await _sample(session, {**FULL, 1: 3000.0}, NOW - timedelta(seconds=30))
    await _sample(session, {**FULL, 1: 9000.0}, NOW - timedelta(hours=2))
    line = (await _get(migrated_db))["recent_w"]
    assert [p["watts"] for p in line] == [pytest.approx(1000), pytest.approx(3000)]
    assert line[0]["time"] < line[1]["time"]


async def test_today_reports_how_much_was_recorded(session, migrated_db):
    await _sample(session, {**FULL, 1: 2000.0}, NOW - timedelta(minutes=10))
    body = await _get(migrated_db)
    assert 0 < body["today_coverage"] < 0.01


async def test_recent_line_skips_a_minute_missing_one_incoming_leg(session, migrated_db):
    await _sample(session, {**FULL, 1: 1000.0, 7: 1000.0}, NOW - timedelta(seconds=90))
    partial = {c: w for c, w in {**FULL, 1: 1000.0}.items() if c != 7}
    await _sample(session, partial, NOW - timedelta(seconds=30))
    assert [p["watts"] for p in (await _get(migrated_db))["recent_w"]] == [pytest.approx(2000)]


async def test_whole_house_label_position_comes_from_its_zone(session, migrated_db):
    await _sample(session, FULL)
    assert (await _get(migrated_db))["whole_house_pin"] == {"x": 63, "y": 84}


async def test_today_is_reused_for_a_minute(session, migrated_db):
    app = _app(migrated_db)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        first = (await client.get("/api/live")).json()["today_kwh"]
        await _sample(session, {**FULL, 1: 9000.0}, NOW - timedelta(minutes=5))
        assert (await client.get("/api/live")).json()["today_kwh"] == first
        app.state.clock = lambda: NOW + timedelta(seconds=61)
        assert (await client.get("/api/live")).json()["today_kwh"] > first


async def test_today_still_counts_when_the_whole_house_zone_is_renamed(session, migrated_db):
    await session.execute(text("UPDATE zones SET name = 'Mains' WHERE kind = 'incoming'"))
    await session.commit()
    try:
        await _sample(session, {**FULL, 1: 2000.0}, NOW - timedelta(minutes=10))
        body = await _get(migrated_db)
    finally:
        await session.execute(text("UPDATE zones SET name = 'Whole House' WHERE kind = 'incoming'"))
        await session.commit()
    assert body["today_kwh"] > 0
