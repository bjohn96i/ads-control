from datetime import date, datetime, timezone

import httpx
import pytest
from sqlalchemy import text

from adscontrol.app import create_app
from adscontrol.config import Settings
from adscontrol.maintenance.repo import import_tasks

pytestmark = pytest.mark.integration

# 11:30 PM Eastern on Nov 2 is already Nov 3 in UTC.
NOW = datetime(2026, 11, 3, 4, 30, tzinfo=timezone.utc)
HEADERS = {"X-Control-Action": "1"}
SEED = {
    "tasks": [
        {
            "name": "HVAC",
            "category": "House",
            "notes": "14 x 25 x 1",
            "interval_months": 3,
            "items": ["Office", "Gym", "Living Room", "Bedroom"],
            "done": [{"on": "2026-08-29"}],
        },
        {
            "name": "Fridge",
            "category": "House",
            "interval_months": 6,
            "done": [{"on": "2026-06-01"}],
        },
        {"name": "Driveway", "category": "House"},
        {
            "name": "Later",
            "category": "House",
            "interval_months": 12,
            "done": [{"on": "2026-10-01"}],
        },
    ]
}


@pytest.fixture
async def api(session, migrated_db):
    await session.execute(text("TRUNCATE tasks CASCADE"))
    await import_tasks(session, SEED)
    await session.commit()
    app = create_app(Settings(database_url=migrated_db), jobs=[], start_jobs=False)
    app.state.clock = lambda: NOW
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _task(api, name) -> dict:
    tasks = (await api.get("/api/maintenance")).json()["tasks"]
    return next(t for t in tasks if t["name"] == name)


async def test_complete_defaults_to_today_local(api):
    fridge = await _task(api, "Fridge")
    r = await api.post(f"/api/maintenance/{fridge['id']}/complete", json={}, headers=HEADERS)
    assert r.status_code == 200
    assert (await _task(api, "Fridge"))["last_done"] == "Nov 2, 2026"


async def test_double_submit_records_one_completion(api, session):
    driveway = await _task(api, "Driveway")
    url = f"/api/maintenance/{driveway['id']}/complete"
    await api.post(url, json={"who": "John"}, headers=HEADERS)
    await api.post(url, json={"who": "Sam"}, headers=HEADERS)
    count = await session.scalar(
        text("SELECT count(*) FROM completions WHERE task_id = :t"), {"t": driveway["id"]}
    )
    assert count == 1


async def test_ticking_two_of_four_rooms_leaves_others_due(api):
    hvac = await _task(api, "HVAC")
    rooms = {i["name"]: i["id"] for i in hvac["items"]}
    await api.post(
        f"/api/maintenance/{hvac['id']}/complete",
        json={"item_ids": [rooms["Office"], rooms["Gym"]], "done_on": "2026-11-01"},
        headers=HEADERS,
    )
    after = await _task(api, "HVAC")
    by_room = {i["name"]: i["last_done"] for i in after["items"]}
    assert by_room["Office"] == "Nov 1, 2026"
    assert by_room["Bedroom"] == "Aug 29, 2026"
    assert after["next_due"] == "2026-11-29"


async def test_completing_a_room_task_without_items_means_all_rooms(api):
    hvac = await _task(api, "HVAC")
    await api.post(f"/api/maintenance/{hvac['id']}/complete", json={}, headers=HEADERS)
    after = await _task(api, "HVAC")
    assert {i["last_done"] for i in after["items"]} == {"Nov 2, 2026"}


async def test_undo_restores_previous_next_due(api):
    fridge = await _task(api, "Fridge")
    before = fridge["next_due"]
    created = await api.post(f"/api/maintenance/{fridge['id']}/complete", json={}, headers=HEADERS)
    assert (await _task(api, "Fridge"))["next_due"] != before
    for cid in created.json()["completion_ids"]:
        assert (
            await api.delete(f"/api/maintenance/completions/{cid}", headers=HEADERS)
        ).status_code == 204
    assert (await _task(api, "Fridge"))["next_due"] == before


async def test_write_without_header_is_rejected(api):
    fridge = await _task(api, "Fridge")
    assert (await api.post(f"/api/maintenance/{fridge['id']}/complete", json={})).status_code == 403
    assert (await api.delete("/api/maintenance/completions/1")).status_code == 403
    assert (await api.patch(f"/api/maintenance/{fridge['id']}", json={})).status_code == 403
    assert (await api.post("/api/maintenance/import", json={"tasks": []})).status_code == 403


async def test_future_date_rejected(api):
    fridge = await _task(api, "Fridge")
    r = await api.post(
        f"/api/maintenance/{fridge['id']}/complete", json={"done_on": "2026-11-03"}, headers=HEADERS
    )
    assert r.status_code == 422


async def test_item_from_another_task_rejected(api):
    hvac = await _task(api, "HVAC")
    fridge = await _task(api, "Fridge")
    r = await api.post(
        f"/api/maintenance/{fridge['id']}/complete",
        json={"item_ids": [hvac["items"][0]["id"]]},
        headers=HEADERS,
    )
    assert r.status_code == 422


async def test_empty_item_list_rejected(api):
    hvac = await _task(api, "HVAC")
    r = await api.post(
        f"/api/maintenance/{hvac['id']}/complete", json={"item_ids": []}, headers=HEADERS
    )
    assert r.status_code == 422


async def test_unknown_task_is_404(api):
    assert (
        await api.post("/api/maintenance/999999/complete", json={}, headers=HEADERS)
    ).status_code == 404


async def test_overdue_sorts_first_then_soonest_then_undated(api):
    names = [t["name"] for t in (await api.get("/api/maintenance")).json()["tasks"]]
    assert names == ["HVAC", "Fridge", "Later", "Driveway"]
    assert (await _task(api, "Fridge"))["overdue"] is False
    assert (await _task(api, "HVAC"))["overdue"] is False


async def test_past_due_task_is_overdue(api, session):
    await session.execute(
        text(
            "UPDATE completions SET done_on = '2026-01-01' WHERE task_id = (SELECT id FROM tasks WHERE name = 'Fridge')"
        )
    )
    await session.commit()
    assert (await _task(api, "Fridge"))["overdue"] is True


async def test_next_item_for_home_strip(api):
    body = (await api.get("/api/maintenance/next")).json()
    assert body["name"] == "HVAC"
    assert body["next_due"] == "2026-11-29"


async def test_patch_sets_and_clears_interval(api):
    driveway = await _task(api, "Driveway")
    url = f"/api/maintenance/{driveway['id']}"
    assert (await api.patch(url, json={"interval_months": 12}, headers=HEADERS)).status_code == 200
    assert (await _task(api, "Driveway"))["interval_months"] == 12
    await api.patch(url, json={"interval_months": None}, headers=HEADERS)
    assert (await _task(api, "Driveway"))["interval_months"] is None
    assert (await api.patch(url, json={"interval_months": 0}, headers=HEADERS)).status_code == 422


async def test_export_import_round_trip(api, session):
    hvac = await _task(api, "HVAC")
    await api.post(
        f"/api/maintenance/{hvac['id']}/complete",
        json={
            "item_ids": [hvac["items"][0]["id"]],
            "who": "Sam",
            "done_on": str(date(2026, 11, 1)),
        },
        headers=HEADERS,
    )
    exported = (await api.get("/api/maintenance/export")).json()
    before = (await api.get("/api/maintenance")).json()
    await session.execute(text("TRUNCATE tasks CASCADE"))
    await session.commit()
    assert (
        await api.post("/api/maintenance/import", json=exported, headers=HEADERS)
    ).status_code == 200
    after = (await api.get("/api/maintenance")).json()
    strip = lambda body: [  # noqa: E731
        (t["name"], t["notes"], t["next_due"], [(i["name"], i["last_done"]) for i in t["items"]])
        for t in body["tasks"]
    ]
    assert strip(after) == strip(before)
    who = await session.scalar(text("SELECT count(*) FROM completions WHERE who = 'Sam'"))
    assert who == 1


async def test_import_dry_run_writes_nothing(api, session):
    body = {"tasks": [{"name": "New", "category": "House"}]}
    r = await api.post("/api/maintenance/import?dry_run=true", json=body, headers=HEADERS)
    assert r.json()["tasks"] == 1
    assert await session.scalar(text("SELECT count(*) FROM tasks WHERE name = 'New'")) == 0


async def test_bad_import_is_422_and_writes_nothing(api, session):
    body = {
        "tasks": [
            {
                "name": "New",
                "category": "House",
                "items": ["A"],
                "done": [{"on": "2026-01-01", "items": ["B"]}],
            }
        ]
    }
    r = await api.post("/api/maintenance/import", json=body, headers=HEADERS)
    assert r.status_code == 422
    assert await session.scalar(text("SELECT count(*) FROM tasks WHERE name = 'New'")) == 0
