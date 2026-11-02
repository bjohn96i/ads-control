"""The maintenance list: read it, mark things done, undo, and back it up."""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, StringConstraints, ValidationError, model_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from adscontrol.maintenance.repo import add_completions, import_tasks, list_tasks
from adscontrol.rates import LOCAL


def require_action(x_control_action: str | None = Header(default=None)) -> None:
    """A browser will not add a custom header cross-site, so a link on another page can't write."""
    if x_control_action != "1":
        raise HTTPException(status_code=403, detail="missing X-Control-Action header")


router = APIRouter(prefix="/api/maintenance")
write = [Depends(require_action)]


class CompleteIn(BaseModel):
    item_ids: list[int] | None = None
    done_on: date | None = None
    who: str | None = Field(default=None, max_length=40)


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class TaskCreate(BaseModel):
    name: Name
    category: Name
    notes: str = ""
    interval_months: int | None = Field(default=None, gt=0)
    items: list[Name] = []

    @model_validator(mode="after")
    def rooms_are_unique(self) -> "TaskCreate":
        if len(set(self.items)) != len(self.items):
            raise ValueError("each room can only be listed once")
        return self


class PatchIn(BaseModel):
    name: Name = None  # type: ignore[assignment]  # optional, but never null
    category: Name = None  # type: ignore[assignment]
    notes: str = None  # type: ignore[assignment]
    interval_months: int | None = Field(default=None, gt=0)

    @model_validator(mode="before")
    @classmethod
    def only_interval_can_be_null(cls, data: dict) -> dict:
        if any(data.get(k, "") is None for k in ("name", "category", "notes")):
            raise ValueError("name, category and notes cannot be null")
        return data


class ItemIn(BaseModel):
    name: Name


def _today(request: Request) -> date:
    return request.app.state.clock().astimezone(LOCAL).date()


async def _sorted_tasks(request: Request) -> list[dict]:
    today = _today(request)
    async with request.app.state.sessions() as session:
        tasks = await list_tasks(session)
    rows = [
        {
            "id": t.id,
            "name": t.name,
            "category": t.category,
            "notes": t.notes,
            "interval_months": t.interval_months,
            "items": [vars(i) for i in t.items],
            "last_done": t.last_done,
            "next_due": t.next_due,
            "overdue": t.next_due is not None and t.next_due < today,
        }
        for t in tasks
    ]
    # Dated tasks first, soonest (so overdue) at the top; the rest keep their list order.
    return sorted(rows, key=lambda r: (r["next_due"] is None, r["next_due"] or date.max))


@router.get("")
async def list_maintenance(request: Request) -> dict:
    return {"tasks": await _sorted_tasks(request)}


@router.get("/next")
async def next_item(request: Request) -> dict | None:
    dated = [t for t in await _sorted_tasks(request) if t["next_due"] is not None]
    return dated[0] if dated else None


@router.post("/{task_id}/complete", dependencies=write)
async def complete(task_id: int, body: CompleteIn, request: Request) -> dict:
    today = _today(request)
    done_on = body.done_on or today
    if done_on > today:
        raise HTTPException(status_code=422, detail="that date is in the future")
    if body.item_ids == []:
        raise HTTPException(status_code=422, detail="choose at least one room")
    async with request.app.state.sessions() as session:
        exists = await session.scalar(text("SELECT 1 FROM tasks WHERE id = :t"), {"t": task_id})
        if not exists:
            raise HTTPException(status_code=404, detail="no such task")
        rows = await session.execute(
            text("SELECT id FROM task_items WHERE task_id = :t"), {"t": task_id}
        )
        own = set(rows.scalars())
        if body.item_ids is not None and not set(body.item_ids) <= own:
            raise HTTPException(status_code=422, detail="that room is not on this task")
        chosen: list[int | None] = body.item_ids if body.item_ids is not None else sorted(own)
        ids = await add_completions(session, task_id, chosen or [None], done_on, who=body.who)
        await session.commit()
    return {"completion_ids": ids}


@router.delete("/completions/{completion_id}", status_code=204, dependencies=write)
async def undo(completion_id: int, request: Request) -> None:
    async with request.app.state.sessions() as session:
        await session.execute(text("DELETE FROM completions WHERE id = :c"), {"c": completion_id})
        await session.commit()


@router.post("", status_code=201, dependencies=write)
async def create_task(body: TaskCreate, request: Request) -> dict:
    async with request.app.state.sessions() as session:
        try:
            task_id = await session.scalar(
                text(
                    """
                    INSERT INTO tasks (name, category, notes, interval_months)
                    VALUES (:name, :category, :notes, :interval_months) RETURNING id
                    """
                ),
                body.model_dump(exclude={"items"}),
            )
            for name in body.items:
                await session.execute(
                    text("INSERT INTO task_items (task_id, name) VALUES (:t, :n)"),
                    {"t": task_id, "n": name},
                )
            await session.commit()
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="that name is already used") from exc
    return {"id": task_id}


# Order matters: /items/{id} must be declared ahead of the /{task_id} routes below it.
@router.patch("/items/{item_id}", dependencies=write)
async def rename_item(item_id: int, body: ItemIn, request: Request) -> dict:
    async with request.app.state.sessions() as session:
        try:
            result = await session.execute(
                text("UPDATE task_items SET name = :n WHERE id = :i"),
                {"n": body.name, "i": item_id},
            )
            await session.commit()
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="that room is already listed") from exc
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="no such room")
    return {"ok": True}


@router.delete("/items/{item_id}", status_code=204, dependencies=write)
async def delete_item(item_id: int, request: Request) -> None:
    async with request.app.state.sessions() as session:
        result = await session.execute(text("DELETE FROM task_items WHERE id = :i"), {"i": item_id})
        await session.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="no such room")


@router.post("/{task_id}/items", status_code=201, dependencies=write)
async def add_item(task_id: int, body: ItemIn, request: Request) -> dict:
    async with request.app.state.sessions() as session:
        if not await session.scalar(text("SELECT 1 FROM tasks WHERE id = :t"), {"t": task_id}):
            raise HTTPException(status_code=404, detail="no such task")
        try:
            item_id = await session.scalar(
                text("INSERT INTO task_items (task_id, name) VALUES (:t, :n) RETURNING id"),
                {"t": task_id, "n": body.name},
            )
            await session.commit()
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="that room is already listed") from exc
    return {"id": item_id}


@router.patch("/{task_id}", dependencies=write)
async def patch(task_id: int, body: PatchIn, request: Request) -> dict:
    fields = body.model_dump(exclude_unset=True)
    async with request.app.state.sessions() as session:
        if not await session.scalar(text("SELECT 1 FROM tasks WHERE id = :t"), {"t": task_id}):
            raise HTTPException(status_code=404, detail="no such task")
        try:
            for column in fields:  # names come from PatchIn, not from the request
                await session.execute(
                    text(f"UPDATE tasks SET {column} = :v WHERE id = :t"),
                    {"v": fields[column], "t": task_id},
                )
            await session.commit()
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="that name is already used") from exc
    return {"ok": True}


@router.delete("/{task_id}", status_code=204, dependencies=write)
async def delete_task(task_id: int, request: Request) -> None:
    async with request.app.state.sessions() as session:
        result = await session.execute(text("DELETE FROM tasks WHERE id = :t"), {"t": task_id})
        await session.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="no such task")


@router.get("/export")
async def export(request: Request) -> dict:
    async with request.app.state.sessions() as session:
        tasks = (await session.execute(text("SELECT * FROM tasks ORDER BY id"))).all()
        items = (await session.execute(text("SELECT * FROM task_items ORDER BY id"))).all()
        done = (await session.execute(text("SELECT * FROM completions ORDER BY done_on, id"))).all()
    names = {i.id: i.name for i in items}
    return {
        "tasks": [
            {
                "name": t.name,
                "category": t.category,
                "notes": t.notes,
                "interval_months": t.interval_months,
                "items": [i.name for i in items if i.task_id == t.id],
                "done": [
                    {
                        "on": d.done_on,
                        "precision": d.precision,
                        "who": d.who,
                        "items": [names[d.item_id]] if d.item_id else [],
                    }
                    for d in done
                    if d.task_id == t.id
                ],
            }
            for t in tasks
        ]
    }


@router.post("/import", dependencies=write)
async def import_(body: dict[str, Any], request: Request, dry_run: bool = False) -> dict:
    async with request.app.state.sessions() as session:
        try:
            counts = await import_tasks(session, body)
        except (ValueError, ValidationError) as exc:
            await session.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if dry_run:
            await session.rollback()
        else:
            await session.commit()
    return counts
