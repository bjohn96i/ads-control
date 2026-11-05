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
    assert (await api.patch(url, json={"repeat_every": 12}, headers=HEADERS)).status_code == 200
    assert (await _task(api, "Driveway"))["repeat_every"] == 12
    await api.patch(url, json={"repeat_every": None}, headers=HEADERS)
    assert (await _task(api, "Driveway"))["repeat_every"] is None
    assert (await api.patch(url, json={"repeat_every": 0}, headers=HEADERS)).status_code == 422


async def test_patch_changes_the_repeat_unit(api):
    fridge = await _task(api, "Fridge")
    url = f"/api/maintenance/{fridge['id']}"
    assert fridge["repeat_unit"] == "month"  # imported from interval_months
    assert (await api.patch(url, json={"repeat_unit": "week"}, headers=HEADERS)).status_code == 200
    fridge = await _task(api, "Fridge")
    assert (fridge["repeat_every"], fridge["repeat_unit"]) == (6, "week")
    assert fridge["next_due"] == "2026-07-13"  # six weeks after Jun 1
    for bad in (None, "year"):
        assert (await api.patch(url, json={"repeat_unit": bad}, headers=HEADERS)).status_code == 422


async def test_a_task_can_repeat_every_few_days(api):
    body = {"name": "Water plants", "category": "House", "repeat_every": 3, "repeat_unit": "day"}
    task_id = (await api.post("/api/maintenance", json=body, headers=HEADERS)).json()["id"]
    await api.post(
        f"/api/maintenance/{task_id}/complete", json={"done_on": "2026-10-28"}, headers=HEADERS
    )
    task = await _task(api, "Water plants")
    assert task["next_due"] == "2026-10-31"
    assert task["overdue"] is True  # today is Nov 2 here


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
    fridge = await _task(api, "Fridge")
    await api.patch(
        f"/api/maintenance/{fridge['id']}", json={"repeat_unit": "week"}, headers=HEADERS
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


async def test_add_task_with_rooms(api):
    r = await api.post(
        "/api/maintenance",
        json={
            "name": "  Dryer Vent ",
            "category": "House",
            "notes": "Back wall",
            "repeat_every": 12,
            "items": ["Laundry", "Roof"],
        },
        headers=HEADERS,
    )
    assert r.status_code == 201
    task = await _task(api, "Dryer Vent")
    assert task["id"] == r.json()["id"]
    assert task["notes"] == "Back wall"
    assert [i["name"] for i in task["items"]] == ["Laundry", "Roof"]
    assert task["last_done"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"name": "   ", "category": "House"},
        {"name": "X", "category": ""},
        {"name": "X", "category": "House", "repeat_every": 0},
        {"name": "X", "category": "House", "repeat_every": 2, "repeat_unit": "fortnight"},
        {"name": "X", "category": "House", "items": ["  "]},
        {"name": "X", "category": "House", "items": ["A", "A"]},
        {"name": "X" * 121, "category": "House"},
    ],
)
async def test_bad_new_task_is_rejected(api, body):
    assert (await api.post("/api/maintenance", json=body, headers=HEADERS)).status_code == 422


async def test_duplicate_task_name_is_409(api):
    r = await api.post(
        "/api/maintenance", json={"name": "Fridge", "category": "House"}, headers=HEADERS
    )
    assert r.status_code == 409


async def test_rename_and_edit_task_keeps_history(api):
    fridge = await _task(api, "Fridge")
    r = await api.patch(
        f"/api/maintenance/{fridge['id']}",
        json={"name": "Fridge Filter", "category": "Kitchen", "notes": "Part 123"},
        headers=HEADERS,
    )
    assert r.status_code == 200
    after = await _task(api, "Fridge Filter")
    assert (after["category"], after["notes"]) == ("Kitchen", "Part 123")
    assert after["last_done"] == fridge["last_done"]


async def test_rename_to_existing_name_is_409(api):
    fridge = await _task(api, "Fridge")
    r = await api.patch(f"/api/maintenance/{fridge['id']}", json={"name": "HVAC"}, headers=HEADERS)
    assert r.status_code == 409


@pytest.mark.parametrize(
    "body", [{"name": "  "}, {"name": None}, {"category": None}, {"notes": None}]
)
async def test_bad_edit_is_rejected(api, body):
    fridge = await _task(api, "Fridge")
    assert (
        await api.patch(f"/api/maintenance/{fridge['id']}", json=body, headers=HEADERS)
    ).status_code == 422


async def test_edit_unknown_task_is_404(api):
    assert (
        await api.patch("/api/maintenance/999999", json={"notes": "x"}, headers=HEADERS)
    ).status_code == 404


async def test_delete_task_removes_it_and_its_history(api, session):
    hvac = await _task(api, "HVAC")
    assert (await api.delete(f"/api/maintenance/{hvac['id']}", headers=HEADERS)).status_code == 204
    assert hvac["name"] not in [
        t["name"] for t in (await api.get("/api/maintenance")).json()["tasks"]
    ]
    left = await session.scalar(
        text("SELECT count(*) FROM completions WHERE task_id = :t"), {"t": hvac["id"]}
    )
    assert left == 0
    assert (await api.delete(f"/api/maintenance/{hvac['id']}", headers=HEADERS)).status_code == 404


async def test_add_rename_and_delete_room(api):
    hvac = await _task(api, "HVAC")
    r = await api.post(
        f"/api/maintenance/{hvac['id']}/items", json={"name": "Attic"}, headers=HEADERS
    )
    assert r.status_code == 201
    item_id = r.json()["id"]
    assert (
        await api.patch(f"/api/maintenance/items/{item_id}", json={"name": "Loft"}, headers=HEADERS)
    ).status_code == 200
    names = [i["name"] for i in (await _task(api, "HVAC"))["items"]]
    assert "Loft" in names and "Attic" not in names
    assert (
        await api.delete(f"/api/maintenance/items/{item_id}", headers=HEADERS)
    ).status_code == 204
    assert "Loft" not in [i["name"] for i in (await _task(api, "HVAC"))["items"]]


async def test_rename_room_keeps_its_history(api):
    hvac = await _task(api, "HVAC")
    gym = next(i for i in hvac["items"] if i["name"] == "Gym")
    await api.patch(
        f"/api/maintenance/items/{gym['id']}", json={"name": "Home Gym"}, headers=HEADERS
    )
    after = next(i for i in (await _task(api, "HVAC"))["items"] if i["id"] == gym["id"])
    assert (after["name"], after["last_done"]) == ("Home Gym", gym["last_done"])


async def test_never_done_room_added_keeps_task_due_from_first_completion(api):
    hvac = await _task(api, "HVAC")
    await api.post(f"/api/maintenance/{hvac['id']}/items", json={"name": "Attic"}, headers=HEADERS)
    assert (await _task(api, "HVAC"))["next_due"] == hvac["next_due"]


async def test_duplicate_room_is_409(api):
    hvac = await _task(api, "HVAC")
    gym = next(i for i in hvac["items"] if i["name"] == "Gym")
    url = f"/api/maintenance/{hvac['id']}/items"
    assert (await api.post(url, json={"name": "Gym"}, headers=HEADERS)).status_code == 409
    assert (
        await api.patch(
            f"/api/maintenance/items/{gym['id']}", json={"name": "Office"}, headers=HEADERS
        )
    ).status_code == 409


async def test_room_routes_404_and_reject_blank(api):
    hvac = await _task(api, "HVAC")
    assert (
        await api.post("/api/maintenance/999999/items", json={"name": "A"}, headers=HEADERS)
    ).status_code == 404
    assert (
        await api.post(f"/api/maintenance/{hvac['id']}/items", json={"name": " "}, headers=HEADERS)
    ).status_code == 422
    assert (
        await api.patch("/api/maintenance/items/999999", json={"name": "A"}, headers=HEADERS)
    ).status_code == 404
    assert (await api.delete("/api/maintenance/items/999999", headers=HEADERS)).status_code == 404


async def test_new_write_routes_need_the_header(api):
    hvac = await _task(api, "HVAC")
    assert (
        await api.post("/api/maintenance", json={"name": "A", "category": "B"})
    ).status_code == 403
    assert (await api.delete(f"/api/maintenance/{hvac['id']}")).status_code == 403
    assert (
        await api.post(f"/api/maintenance/{hvac['id']}/items", json={"name": "A"})
    ).status_code == 403
    assert (await api.patch("/api/maintenance/items/1", json={"name": "A"})).status_code == 403
    assert (await api.delete("/api/maintenance/items/1")).status_code == 403
