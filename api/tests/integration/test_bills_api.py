from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import text

from adscontrol.api.bills import MAX_UPLOAD_BYTES
from adscontrol.app import create_app
from adscontrol.config import Settings

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 2, 16, 0, tzinfo=timezone.utc)
HEADERS = {"X-Control-Action": "1"}
BILL = {
    "period_start": "2026-09-24",
    "period_end": "2026-10-23",
    "on_peak_kwh": 30,
    "off_peak_kwh": 483,
    "super_off_peak_kwh": 546,
    "total_kwh": 1058,
    "current_service": 126.46,
    "ecc": 11.02,
    "franchise_fee": 1.65,
    "sales_tax": 11.13,
    "actual_charge": 150.26,
    "budget_payment": 248.0,
    "budget_difference": -97.74,
    "running_difference": -260.13,
}


@pytest.fixture
async def api(session, migrated_db):
    await session.execute(text("TRUNCATE bills"))
    await session.commit()
    app = create_app(Settings(database_url=migrated_db), jobs=[], start_jobs=False)
    app.state.clock = lambda: NOW
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _count(session) -> int:
    return await session.scalar(text("SELECT count(*) FROM bills"))


async def test_save_and_list_newest_first(api):
    assert (await api.post("/api/bills", json=BILL, headers=HEADERS)).status_code == 201
    older = {
        **BILL,
        "period_start": "2026-08-25",
        "period_end": "2026-09-23",
        "actual_charge": 200.0,
    }
    await api.post("/api/bills", json=older, headers=HEADERS)
    bills = (await api.get("/api/bills")).json()["bills"]
    assert [b["period_end"] for b in bills] == ["2026-10-23", "2026-09-23"]
    assert bills[0]["actual_charge"] == 150.26


async def test_latest_is_for_the_home_strip(api):
    assert (await api.get("/api/bills/latest")).json() is None
    await api.post("/api/bills", json=BILL, headers=HEADERS)
    assert (await api.get("/api/bills/latest")).json()["actual_charge"] == 150.26


async def test_parse_saves_nothing(api, session):
    r = await api.post("/api/bills/parse", content=b"not a pdf", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["actual_charge"] is None
    assert await _count(session) == 0


async def test_oversized_upload_is_rejected(api):
    r = await api.post("/api/bills/parse", content=b"x" * (MAX_UPLOAD_BYTES + 1), headers=HEADERS)
    assert r.status_code == 413


async def test_same_period_twice_is_409(api):
    await api.post("/api/bills", json=BILL, headers=HEADERS)
    assert (await api.post("/api/bills", json=BILL, headers=HEADERS)).status_code == 409


@pytest.mark.parametrize(
    "change",
    [
        {"period_end": "2026-09-01"},
        {"total_kwh": -1},
        {"actual_charge": -5},
        {"actual_charge": None},
        {"total_kwh": None},
    ],
)
async def test_bad_bill_is_rejected(api, change):
    assert (
        await api.post("/api/bills", json={**BILL, **change}, headers=HEADERS)
    ).status_code == 422


async def test_budget_fields_are_optional(api):
    body = {k: BILL[k] for k in ("period_start", "period_end", "total_kwh", "actual_charge")}
    assert (await api.post("/api/bills", json=body, headers=HEADERS)).status_code == 201


async def test_writes_need_the_header(api):
    assert (await api.post("/api/bills", json=BILL)).status_code == 403
    assert (await api.post("/api/bills/parse", content=b"x")).status_code == 403
    assert (await api.delete("/api/bills/1")).status_code == 403
    assert (await api.post("/api/bills/import", json={"bills": []})).status_code == 403


async def test_delete_and_404(api, session):
    bill_id = (await api.post("/api/bills", json=BILL, headers=HEADERS)).json()["id"]
    assert (await api.delete(f"/api/bills/{bill_id}", headers=HEADERS)).status_code == 204
    assert await _count(session) == 0
    assert (await api.delete(f"/api/bills/{bill_id}", headers=HEADERS)).status_code == 404
    assert (await api.get(f"/api/bills/{bill_id}/compare")).status_code == 404


async def _fill(session, start, end, watts):
    for channel in (1, 7):
        await session.execute(
            text(
                """
                INSERT INTO channel_readings SELECT t, :c, :w, 120, 1, 1, 0 FROM generate_series(
                    CAST(:s AS timestamptz), CAST(:e AS timestamptz) - INTERVAL '10 seconds', INTERVAL '10 seconds') t
                """
            ),
            dict(c=channel, w=watts, s=start, e=end),
        )
    await session.commit()


async def test_compare_reports_coverage_with_gaps(api, session):
    body = {**BILL, "period_start": "2026-10-20", "period_end": "2026-10-23", "total_kwh": 100}
    bill_id = (await api.post("/api/bills", json=body, headers=HEADERS)).json()["id"]
    start = datetime(2026, 10, 20, 4, 0, tzinfo=timezone.utc)  # local midnight
    await _fill(session, start, start + timedelta(days=2), 500.0)
    result = (await api.get(f"/api/bills/{bill_id}/compare")).json()
    assert result["billed_kwh"] == 100
    assert result["measured_kwh"] == pytest.approx(48.0)
    assert result["coverage"] == pytest.approx(0.5, abs=0.01)
    assert result["difference_pct"] is None


async def test_compare_with_full_coverage_gives_a_difference(api, session):
    body = {**BILL, "period_start": "2026-10-20", "period_end": "2026-10-20", "total_kwh": 20}
    bill_id = (await api.post("/api/bills", json=body, headers=HEADERS)).json()["id"]
    start = datetime(2026, 10, 20, 4, 0, tzinfo=timezone.utc)
    await _fill(session, start, start + timedelta(days=1), 500.0)
    result = (await api.get(f"/api/bills/{bill_id}/compare")).json()
    assert result["coverage"] == pytest.approx(1.0)
    assert result["difference_pct"] == pytest.approx(20.0)


async def test_bill_range_starts_after_the_latest_bill(api, session):
    await api.post("/api/bills", json=BILL, headers=HEADERS)
    body = (await api.get("/api/energy/ranking?range=bill")).json()
    assert body["start"] == "2026-10-24T00:00:00-04:00"
    assert body["since_bill"] is True


async def test_export_import_round_trip(api, session):
    await api.post("/api/bills", json=BILL, headers=HEADERS)
    exported = (await api.get("/api/bills/export")).json()
    await session.execute(text("TRUNCATE bills"))
    await session.commit()
    r = await api.post("/api/bills/import", json=exported, headers=HEADERS)
    assert r.json()["bills"] == 1
    r = await api.post("/api/bills/import", json=exported, headers=HEADERS)
    assert r.json()["bills"] == 0
    assert (await api.get("/api/bills/latest")).json()["running_difference"] == -260.13


async def test_compare_still_works_when_the_whole_house_zone_is_renamed(api, session):
    body = {**BILL, "period_start": "2026-10-20", "period_end": "2026-10-20", "total_kwh": 20}
    bill_id = (await api.post("/api/bills", json=body, headers=HEADERS)).json()["id"]
    await session.execute(text("UPDATE zones SET name = 'Mains' WHERE kind = 'incoming'"))
    await session.commit()
    try:
        response = await api.get(f"/api/bills/{bill_id}/compare")
    finally:
        await session.execute(text("UPDATE zones SET name = 'Whole House' WHERE kind = 'incoming'"))
        await session.commit()
    assert response.status_code == 200


async def test_an_oversized_upload_is_refused_without_reading_it_all(api):
    sent = 0

    async def chunks():
        nonlocal sent
        for _ in range(100):
            sent += 1
            yield b"x" * 1_000_000

    r = await api.post("/api/bills/parse", content=chunks(), headers=HEADERS)
    assert r.status_code == 413
    assert sent * 1_000_000 <= MAX_UPLOAD_BYTES + 2_000_000
