"""Rough dates and when a task next comes due."""

import calendar
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Done:
    on: date
    item_id: int | None


def format_rough(day: date, precision: str) -> str:
    if precision == "month":
        return f"{day:%B} {day.year}"
    if precision == "mid_month":
        return f"mid {day:%B} {day.year}"
    return f"{day:%b} {day.day}, {day.year}"


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    year, month = index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def next_due(interval_months: int | None, item_ids: list[int], done: list[Done]) -> date | None:
    if interval_months is None or not done:
        return None
    if not item_ids:
        return _add_months(max(d.on for d in done), interval_months)
    # A room that was skipped keeps the whole task due, so go by the room done longest ago.
    # A room never done counts from the task's first completion.
    latest = [max((d.on for d in done if d.item_id == i), default=None) for i in item_ids]
    first = min(d.on for d in done)
    return _add_months(min(on or first for on in latest), interval_months)
