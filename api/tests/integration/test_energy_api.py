from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import text

from adscontrol.app import create_app
from adscontrol.config import Settings
from adscontrol.energy import energy_by_zone

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 20, 16, 0, tzinfo=timezone.utc)
DISHWASHER, WASHER, BLACK, RED = 3, 9, 1, 7


async def _fill(session, start, end, by_channel: dict[int, float]):
    for channel, watts in by_channel.items():
        await session.execute(
            text(
                """
                INSERT INTO channel_readings
                SELECT t, :c, :w, 120, 1, 1, 0 FROM generate_series(
                    CAST(:s AS timestamptz), CAST(:e AS timestamptz) - INTERVAL '10 seconds', INTERVAL '10 seconds') AS t
                """
            ),
            dict(c=channel, w=watts, s=start, e=end),
        )
    await session.commit()


@pytest.fixture
async def api(session, migrated_db):
    await session.execute(text("UPDATE zones SET multiplier = 1"))
    await session.commit()
    app = create_app(Settings(database_url=migrated_db), jobs=[], start_jobs=False)
    app.state.clock = lambda: NOW
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


def _zone(body, name):
    return next(z for z in body["zones"] if z["name"] == name)


async def test_zones_rank_by_kwh_descending(api, session):
    start = NOW - timedelta(hours=3)
    await _fill(session, start, NOW, {DISHWASHER: 500.0, WASHER: 100.0, BLACK: 700.0, RED: 0.0})
    body = (await api.get("/api/energy/ranking?range=7d")).json()
    names = [z["name"] for z in body["zones"]]
    assert names[:2] == ["Dishwasher", "Washer"]
    assert "Whole House" not in names
    assert _zone(body, "Dishwasher")["kwh"] == pytest.approx(1.5)
    assert _zone(body, "Dishwasher")["share"] == pytest.approx(1.5 / 2.1)


async def test_cost_prices_each_period_separately(api, session):
    # 3 PM and 3 AM Eastern on July days, same kWh, very different price.
    afternoon = datetime(2026, 7, 15, 19, 0, tzinfo=timezone.utc)
    night = datetime(2026, 7, 15, 7, 0, tzinfo=timezone.utc)
    await _fill(session, afternoon, afternoon + timedelta(hours=1), {DISHWASHER: 1000.0})
    await _fill(session, night, night + timedelta(hours=1), {WASHER: 1000.0})
    energy = {
        e.name: e for e in await energy_by_zone(session, night, afternoon + timedelta(hours=1))
    }
    assert energy["Dishwasher"].est_cost == pytest.approx(0.416, abs=0.001)
    assert energy["Washer"].est_cost == pytest.approx(0.0673, abs=0.001)


async def test_past_energy_keeps_the_rate_that_applied_then(api, session):
    await session.execute(
        text(
            "INSERT INTO rate_versions SELECT DATE '2026-10-01', on_peak_c * 2, off_peak_c * 2, super_off_peak_c * 2, basic_per_day, adder_factor, 'test' FROM rate_versions WHERE effective_from = '2026-06-01'"
        )
    )
    await session.commit()
    try:
        before = datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc)  # 11 AM Eastern, off-peak
        after = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
        await _fill(session, before, before + timedelta(hours=1), {DISHWASHER: 1000.0})
        await _fill(session, after, after + timedelta(hours=1), {WASHER: 1000.0})
        energy = {
            e.name: e for e in await energy_by_zone(session, before, after + timedelta(hours=1))
        }
        assert energy["Washer"].est_cost == pytest.approx(energy["Dishwasher"].est_cost * 2)
    finally:
        await session.execute(text("DELETE FROM rate_versions WHERE effective_from = '2026-10-01'"))
        await session.commit()


async def test_unmetered_line_present(api, session):
    start = NOW - timedelta(hours=1)
    await _fill(session, start, NOW, {BLACK: 600.0, RED: 100.0, DISHWASHER: 500.0})
    body = (await api.get("/api/energy/ranking?range=7d")).json()
    assert body["whole_house"]["kwh"] == pytest.approx(0.7)
    assert body["unmetered"]["kwh"] == pytest.approx(0.2)


async def test_charger_estimate_is_its_own_line(api, session):
    start = NOW - timedelta(hours=1)
    await _fill(session, start, NOW, {BLACK: 4000.0, RED: 4000.0, DISHWASHER: 100.0})
    body = (await api.get("/api/energy/ranking?range=7d")).json()
    assert body["charger_estimate"]["kwh"] == pytest.approx(7.9, abs=0.05)
    assert body["charger_estimate"]["est_cost"] > 0
    assert body["unmetered"]["kwh"] == pytest.approx(0, abs=0.05)


async def test_small_background_is_not_the_charger(api, session):
    start = NOW - timedelta(hours=1)
    await _fill(session, start, NOW, {BLACK: 400.0, RED: 100.0, DISHWASHER: 100.0})
    body = (await api.get("/api/energy/ranking?range=7d")).json()
    assert body["charger_estimate"]["kwh"] == 0
    assert body["unmetered"]["kwh"] == pytest.approx(0.4)


async def test_low_coverage_is_returned(api, session):
    await _fill(session, NOW - timedelta(hours=1), NOW, {BLACK: 500.0, RED: 0.0, DISHWASHER: 100.0})
    body = (await api.get("/api/energy/ranking?range=7d")).json()
    assert body["whole_house"]["coverage"] < 0.01


async def test_unknown_range_is_422(api):
    assert (await api.get("/api/energy/ranking?range=forever")).status_code == 422


async def test_bill_range_without_a_bill_is_last_30_days(api, session):
    await _fill(
        session,
        NOW - timedelta(days=20),
        NOW - timedelta(days=20) + timedelta(hours=1),
        {DISHWASHER: 1000.0},
    )
    bill = (await api.get("/api/energy/ranking?range=bill")).json()
    assert _zone(bill, "Dishwasher")["kwh"] == pytest.approx(1.0)
    assert bill["since_bill"] is False
    assert (bill["start"], bill["end"]) == (
        (await api.get("/api/energy/ranking?range=30d")).json()["start"],
        (await api.get("/api/energy/ranking?range=30d")).json()["end"],
    )


async def test_overnight_min_ignores_daytime(api, session):
    night = datetime(2026, 10, 18, 6, 0, tzinfo=timezone.utc)  # 2 AM Eastern
    await _fill(session, night, night + timedelta(hours=1), {DISHWASHER: 40.0})
    day = datetime(2026, 10, 18, 18, 0, tzinfo=timezone.utc)  # 2 PM Eastern
    await _fill(session, day, day + timedelta(hours=1), {DISHWASHER: 5.0})
    zone_id = await session.scalar(text("SELECT id FROM zones WHERE name = 'Dishwasher'"))
    body = (await api.get(f"/api/energy/zones/{zone_id}?range=7d")).json()
    assert body["overnight_min_w"] == pytest.approx(40)


async def test_zone_with_no_nights_has_no_overnight_min(api, session):
    zone_id = await session.scalar(text("SELECT id FROM zones WHERE name = 'Washer'"))
    body = (await api.get(f"/api/energy/zones/{zone_id}?range=7d")).json()
    assert body["overnight_min_w"] is None


async def test_series_leaves_gaps_as_null(api, session):
    a = NOW - timedelta(hours=5)
    await _fill(session, a, a + timedelta(hours=1), {DISHWASHER: 100.0})
    b = NOW - timedelta(hours=2)
    await _fill(session, b, b + timedelta(hours=1), {DISHWASHER: 300.0})
    zone_id = await session.scalar(text("SELECT id FROM zones WHERE name = 'Dishwasher'"))
    series = (await api.get(f"/api/energy/zones/{zone_id}?range=7d")).json()["series"]
    watts = [p["watts"] for p in series]
    first = watts.index(100.0)
    assert watts[first : first + 4] == [100.0, None, None, 300.0]


async def test_series_applies_multiplier_and_sums_channels(api, session):
    await session.execute(text("UPDATE zones SET multiplier = 2 WHERE name = 'Dryer'"))
    await session.commit()
    a = NOW - timedelta(hours=2)
    await _fill(session, a, a + timedelta(hours=1), {5: 100.0, 11: 50.0})
    zone_id = await session.scalar(text("SELECT id FROM zones WHERE name = 'Dryer'"))
    series = (await api.get(f"/api/energy/zones/{zone_id}?range=7d")).json()["series"]
    assert 300.0 in [p["watts"] for p in series]


async def test_unknown_zone_is_404(api):
    assert (await api.get("/api/energy/zones/999999?range=7d")).status_code == 404


async def test_ranking_names_each_zones_room_and_the_whole_house_zone(api, session):
    body = (await api.get("/api/energy/ranking?range=7d")).json()
    assert _zone(body, "Dishwasher")["room"] == "Kitchen"
    whole_id = await session.scalar(text("SELECT id FROM zones WHERE kind = 'incoming'"))
    assert body["whole_house"]["id"] == whole_id


async def test_room_series_adds_its_circuits(api, session):
    a = NOW - timedelta(hours=2)
    await _fill(session, a, a + timedelta(hours=1), {2: 100.0, 3: 50.0, 8: 25.0})
    body = (await api.get("/api/energy/rooms/Kitchen?range=7d")).json()
    assert body["name"] == "Kitchen"
    assert 175.0 in [p["watts"] for p in body["series"]]


async def test_room_hour_missing_a_circuit_is_a_gap_not_a_low(api, session):
    a = NOW - timedelta(hours=2)
    await _fill(session, a, a + timedelta(hours=1), {2: 100.0, 3: 50.0})
    series = (await api.get("/api/energy/rooms/Kitchen?range=7d")).json()["series"]
    assert all(p["watts"] is None for p in series)


async def test_unknown_room_is_404(api):
    assert (await api.get("/api/energy/rooms/Attic?range=7d")).status_code == 404


async def test_bill_series_keeps_every_hour_across_the_dst_change(session, migrated_db):
    await session.execute(text("TRUNCATE bills"))
    await session.execute(
        text(
            "INSERT INTO bills (period_start, period_end, total_kwh, actual_charge) "
            "VALUES ('2026-09-24', '2026-10-23', 1058, 150.26)"
        )
    )
    await session.commit()
    app = create_app(Settings(database_url=migrated_db), jobs=[], start_jobs=False)
    app.state.clock = lambda: datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
    zone_id = await session.scalar(text("SELECT id FROM zones WHERE name = 'Dishwasher'"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        series = (await c.get(f"/api/energy/zones/{zone_id}?range=bill")).json()["series"]
    await session.execute(text("TRUNCATE bills"))
    await session.commit()
    times = [datetime.fromisoformat(p["time"]) for p in series]
    assert {b - a for a, b in zip(times, times[1:], strict=False)} == {timedelta(hours=1)}


async def test_a_room_name_with_a_slash_still_opens(api, session):
    await session.execute(text("UPDATE zones SET room = 'Up/Down' WHERE room = 'Kitchen'"))
    await session.commit()
    try:
        response = await api.get("/api/energy/rooms/Up%2FDown?range=7d")
    finally:
        await session.execute(text("UPDATE zones SET room = 'Kitchen' WHERE room = 'Up/Down'"))
        await session.commit()
    assert response.status_code == 200
    assert response.json()["name"] == "Up/Down"
