from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from adscontrol.maintenance.repo import import_tasks, list_tasks

pytestmark = pytest.mark.integration

SEED = {
    "tasks": [
        {
            "name": "HVAC Filters",
            "category": "House",
            "notes": "14 x 25 x 1",
            "interval_months": 3,
            "items": ["John's Office", "Gym", "Living Room", "Primary Bedroom"],
            "done": [
                {"on": "2026-05-23"},
                {"on": "2026-08-29", "items": ["John's Office", "Gym"]},
            ],
        },
        {
            "name": "Fridge Filter",
            "category": "House",
            "done": [{"on": "2026-05-01", "precision": "month"}],
        },
        {"name": "Power Wash Driveway", "category": "House"},
        {
            "name": "Windows",
            "category": "Deep Cleaning",
            "items": ["Gym", "Laundry"],
            "done": [{"on": "2026-04-19", "items": ["Gym"]}],
        },
    ]
}


@pytest.fixture(autouse=True)
async def clean(session):
    await session.execute(text("TRUNCATE tasks CASCADE"))
    await session.commit()


def _named(tasks, name):
    return next(t for t in tasks if t.name == name)


async def test_import_creates_tasks_items_and_history(session):
    await import_tasks(session, SEED)
    await session.commit()
    tasks = await list_tasks(session)
    assert len(tasks) == 4
    assert _named(tasks, "HVAC Filters").notes == "14 x 25 x 1"
    fridge = _named(tasks, "Fridge Filter")
    assert fridge.last_done == "May 2026"


async def test_import_is_idempotent(session):
    await import_tasks(session, SEED)
    await import_tasks(session, SEED)
    await session.commit()
    assert await session.scalar(text("SELECT count(*) FROM tasks")) == 4
    assert await session.scalar(text("SELECT count(*) FROM task_items")) == 6
    assert await session.scalar(text("SELECT count(*) FROM completions")) == 8


async def test_import_does_not_overwrite_later_edits(session):
    await import_tasks(session, SEED)
    await session.execute(text("UPDATE tasks SET notes = 'edited' WHERE name = 'HVAC Filters'"))
    await import_tasks(session, SEED)
    await session.commit()
    assert _named(await list_tasks(session), "HVAC Filters").notes == "edited"


async def test_import_preserves_never_done_items(session):
    await import_tasks(session, SEED)
    await session.commit()
    tasks = await list_tasks(session)
    assert _named(tasks, "Power Wash Driveway").last_done is None
    laundry = next(i for i in _named(tasks, "Windows").items if i.name == "Laundry")
    assert laundry.last_done is None


async def test_hvac_8_29_is_partial(session):
    await import_tasks(session, SEED)
    await session.commit()
    hvac = _named(await list_tasks(session), "HVAC Filters")
    by_room = {i.name: i.last_done for i in hvac.items}
    assert by_room["Gym"] == "Aug 29, 2026"
    assert by_room["Living Room"] == "May 23, 2026"
    assert hvac.next_due == date(2026, 8, 23)


async def test_unknown_item_in_history_is_rejected(session):
    bad = {
        "tasks": [
            {
                "name": "X",
                "category": "House",
                "items": ["A"],
                "done": [{"on": "2026-01-01", "items": ["B"]}],
            }
        ]
    }
    with pytest.raises(ValueError, match="B"):
        await import_tasks(session, bad)


async def test_bad_precision_is_rejected(session):
    bad = {
        "tasks": [
            {
                "name": "X",
                "category": "House",
                "done": [{"on": "2026-01-01", "precision": "fortnight"}],
            }
        ]
    }
    with pytest.raises(ValidationError):
        await import_tasks(session, bad)
