from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import text

from adscontrol.app import create_app
from adscontrol.config import Settings
from adscontrol.detect.rules import Finding
from adscontrol.detect.store import record_findings, run_detection

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 21, 8, 30, tzinfo=timezone.utc)
FINDING = Finding("anomaly", "Unusually high: 600 W, usually about 20 W", {"watts": 600.0})


@pytest.fixture
async def zone_id(session):
    await session.execute(text("TRUNCATE findings"))
    await session.commit()
    return await session.scalar(text("SELECT id FROM zones WHERE name = 'Dishwasher'"))


async def _open(session) -> list:
    rows = await session.execute(text("SELECT * FROM findings WHERE resolved_at IS NULL"))
    return rows.all()


async def test_repeat_updates_last_seen_not_new_row(session, zone_id):
    await record_findings(session, {zone_id: [FINDING]}, NOW)
    later = NOW + timedelta(minutes=15)
    await record_findings(session, {zone_id: [FINDING]}, later)
    rows = await _open(session)
    assert len(rows) == 1
    assert rows[0].opened_at == NOW
    assert rows[0].last_seen == later


async def test_finding_resolves_after_24h_clear(session, zone_id):
    await record_findings(session, {zone_id: [FINDING]}, NOW)
    await record_findings(session, {zone_id: []}, NOW + timedelta(hours=23))
    assert len(await _open(session)) == 1
    await record_findings(session, {zone_id: []}, NOW + timedelta(hours=25))
    assert await _open(session) == []


async def test_return_after_resolving_opens_a_new_row(session, zone_id):
    await record_findings(session, {zone_id: [FINDING]}, NOW)
    await record_findings(session, {zone_id: []}, NOW + timedelta(hours=25))
    await record_findings(session, {zone_id: [FINDING]}, NOW + timedelta(hours=26))
    assert len(await _open(session)) == 1
    assert await session.scalar(text("SELECT count(*) FROM findings")) == 2


async def test_run_detection_finds_a_real_anomaly_from_recorded_readings(session, zone_id):
    last = NOW.replace(minute=0)
    await session.execute(
        text(
            """
            INSERT INTO channel_readings
            SELECT t, 3, CASE WHEN t >= :spike THEN 600 ELSE 20 END, 120, 1, 1, 0
            FROM generate_series(CAST(:start AS timestamptz), CAST(:end AS timestamptz) - INTERVAL '10 seconds', INTERVAL '10 seconds') AS t
            """
        ),
        {"spike": last - timedelta(hours=2), "start": last - timedelta(days=16), "end": last},
    )
    await session.commit()
    await run_detection(session, NOW)
    rows = await _open(session)
    assert [(r.zone_id, r.kind) for r in rows] == [(zone_id, "anomaly")]
    assert "600 W" in rows[0].evidence["summary"]


async def test_live_sets_flagged_on_open_finding(session, zone_id, migrated_db):
    await record_findings(session, {zone_id: [FINDING]}, NOW)
    await session.execute(
        text(
            "INSERT INTO channel_readings SELECT :t, c, 0, 120, 1, 1, 0 FROM generate_series(1, 18) c"
        ),
        {"t": NOW},
    )
    await session.commit()
    app = create_app(Settings(database_url=migrated_db), jobs=[], start_jobs=False)
    app.state.clock = lambda: NOW
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        zones = (await c.get("/api/live")).json()["zones"]
        detail = (await c.get(f"/api/energy/zones/{zone_id}?range=7d")).json()
    flagged = {z["name"] for z in zones if z["flagged"]}
    assert flagged == {"Dishwasher"}
    assert detail["flags"][0]["kind"] == "anomaly"
    assert "600 W" in detail["flags"][0]["summary"]
