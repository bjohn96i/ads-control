"""Maintenance storage: listing with computed dates, and the import that seeds and restores it."""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from adscontrol.maintenance.dates import Done, Unit, format_rough, next_due


class DoneIn(BaseModel):
    on: date
    precision: Literal["day", "month", "mid_month"] = "day"
    who: str | None = None
    items: list[str] | None = None  # None means every item on the task


class TaskIn(BaseModel):
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    notes: str = ""
    repeat_every: int | None = Field(default=None, gt=0)
    repeat_unit: Unit = "month"
    items: list[str] = []
    done: list[DoneIn] = []

    @model_validator(mode="before")
    @classmethod
    def months_from_older_files(cls, data: dict) -> dict:
        # Backups and the seed file from before repeat units say interval_months.
        if isinstance(data, dict) and "interval_months" in data and "repeat_every" not in data:
            data = {**data, "repeat_every": data["interval_months"], "repeat_unit": "month"}
        return data


class ImportIn(BaseModel):
    tasks: list[TaskIn]


@dataclass(frozen=True)
class ItemView:
    id: int
    name: str
    last_done: str | None


@dataclass(frozen=True)
class TaskView:
    id: int
    name: str
    category: str
    notes: str
    repeat_every: int | None
    repeat_unit: Unit
    items: list[ItemView]
    last_done: str | None
    next_due: date | None
    last_completion_id: int | None


_ADD_COMPLETION = text(
    """
    INSERT INTO completions (task_id, item_id, done_on, precision, who)
    VALUES (:task_id, :item_id, :done_on, :precision, :who)
    ON CONFLICT (task_id, COALESCE(item_id, 0), done_on) DO NOTHING
    RETURNING id
    """
)


async def add_completions(
    session: AsyncSession,
    task_id: int,
    item_ids: list[int | None],
    done_on: date,
    precision: str = "day",
    who: str | None = None,
) -> list[int]:
    """Records each item once; a repeat of the same day is ignored."""
    created = []
    for item_id in item_ids:
        row = await session.execute(
            _ADD_COMPLETION,
            dict(task_id=task_id, item_id=item_id, done_on=done_on, precision=precision, who=who),
        )
        created.extend(row.scalars().all())
    return created


async def import_tasks(session: AsyncSession, raw: dict) -> dict[str, int]:
    """Adds what is missing. Never overwrites a task or removes history."""
    data = ImportIn.model_validate(raw)
    counts = {"tasks": 0, "completions": 0}
    for task in data.tasks:
        inserted = await session.scalar(
            text(
                """
                INSERT INTO tasks (name, category, notes, repeat_every, repeat_unit)
                VALUES (:name, :category, :notes, :repeat_every, :repeat_unit)
                ON CONFLICT (name) DO NOTHING RETURNING id
                """
            ),
            dict(
                name=task.name,
                category=task.category,
                notes=task.notes,
                repeat_every=task.repeat_every,
                repeat_unit=task.repeat_unit,
            ),
        )
        counts["tasks"] += inserted is not None
        task_id = inserted or await session.scalar(
            text("SELECT id FROM tasks WHERE name = :name"), {"name": task.name}
        )
        for item in task.items:
            await session.execute(
                text(
                    "INSERT INTO task_items (task_id, name) VALUES (:t, :n) ON CONFLICT DO NOTHING"
                ),
                {"t": task_id, "n": item},
            )
        rows = await session.execute(
            text("SELECT id, name FROM task_items WHERE task_id = :t"), {"t": task_id}
        )
        by_name = {r.name: r.id for r in rows}
        for done in task.done:
            names = task.items if done.items is None else done.items
            unknown = [n for n in names if n not in by_name]
            if unknown:
                raise ValueError(f"{task.name}: unknown items {unknown}")
            item_ids: list[int | None] = [by_name[n] for n in names] or [None]
            created = await add_completions(
                session, task_id, item_ids, done.on, done.precision, done.who
            )
            counts["completions"] += len(created)
    return counts


async def list_tasks(session: AsyncSession) -> list[TaskView]:
    tasks = (
        await session.execute(
            text(
                "SELECT id, name, category, notes, repeat_every, repeat_unit FROM tasks ORDER BY id"
            )
        )
    ).all()
    items = (
        await session.execute(text("SELECT id, task_id, name FROM task_items ORDER BY id"))
    ).all()
    done = (
        await session.execute(
            text(
                "SELECT id, task_id, item_id, done_on, precision FROM completions ORDER BY done_on, id"
            )
        )
    ).all()

    views = []
    for task in tasks:
        own_items = [i for i in items if i.task_id == task.id]
        own_done = [d for d in done if d.task_id == task.id]
        last = own_done[-1] if own_done else None
        item_views = []
        for item in own_items:
            latest = [d for d in own_done if d.item_id == item.id]
            item_views.append(
                ItemView(
                    item.id,
                    item.name,
                    format_rough(latest[-1].done_on, latest[-1].precision) if latest else None,
                )
            )
        views.append(
            TaskView(
                id=task.id,
                name=task.name,
                category=task.category,
                notes=task.notes,
                repeat_every=task.repeat_every,
                repeat_unit=task.repeat_unit,
                items=item_views,
                last_done=format_rough(last.done_on, last.precision) if last else None,
                next_due=next_due(
                    task.repeat_every,
                    task.repeat_unit,
                    [i.id for i in own_items],
                    [Done(d.done_on, d.item_id) for d in own_done],
                ),
                last_completion_id=last.id if last else None,
            )
        )
    return views
