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


async def test_month_coverage_reports_gap(session, migrated_db):
    await _sample(session, {**FULL, 1: 1000.0})
    body = await _get(migrated_db)
    assert body["month_coverage"] < 0.01
    assert body["month_kwh"] >= 0
