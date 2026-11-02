from datetime import date

import pytest

from adscontrol.maintenance.dates import Done, format_rough, next_due


@pytest.mark.parametrize(
    ("day", "precision", "text"),
    [
        (date(2026, 10, 18), "day", "Oct 18, 2026"),
        (date(2026, 5, 1), "month", "May 2026"),
        (date(2026, 6, 15), "mid_month", "mid June 2026"),
    ],
)
def test_format_rough_never_shows_false_day(day, precision, text):
    assert format_rough(day, precision) == text


def test_next_due_with_interval():
    assert next_due(3, [], [Done(date(2026, 8, 29), None)]) == date(2026, 11, 29)


def test_next_due_keeps_month_end_valid():
    assert next_due(1, [], [Done(date(2026, 1, 31), None)]) == date(2026, 2, 28)


def test_next_due_none_without_interval():
    assert next_due(None, [], [Done(date(2026, 8, 29), None)]) is None


def test_next_due_none_when_never_done():
    assert next_due(3, [], []) is None


def test_next_due_uses_the_latest_completion():
    done = [
        Done(date(2026, 2, 6), None),
        Done(date(2026, 8, 29), None),
        Done(date(2026, 5, 23), None),
    ]
    assert next_due(3, [], done) == date(2026, 11, 29)


def test_next_due_for_item_task_uses_oldest_item():
    done = [
        Done(date(2026, 5, 23), 1),
        Done(date(2026, 5, 23), 2),
        Done(date(2026, 8, 29), 1),
    ]
    assert next_due(3, [1, 2], done) == date(2026, 8, 23)


def test_item_never_done_counts_from_the_tasks_first_completion():
    done = [Done(date(2026, 5, 23), 1), Done(date(2026, 8, 29), 1)]
    assert next_due(3, [1, 2], done) == date(2026, 8, 23)
