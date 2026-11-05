import asyncio

import pytest

from adscontrol import scheduler
from adscontrol.scheduler import Job, Scheduler

real_sleep = asyncio.sleep


async def test_slow_poll_does_not_stretch_the_interval(monkeypatch):
    """Samples are counted as exactly one interval each, so the loop must keep that cadence."""
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)
        raise asyncio.CancelledError

    async def slow_poll() -> None:
        await real_sleep(0.03)

    monkeypatch.setattr(scheduler.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await Scheduler([], {})._loop(Job("refoss", 0.1, slow_poll))
    assert waits[0] == pytest.approx(0.07, abs=0.015)


async def test_a_late_wake_up_is_made_up_on_the_next_wait(monkeypatch):
    """Small sleep overruns must not add up over thousands of samples a day."""
    waits: list[float] = []

    async def late_sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 2:
            raise asyncio.CancelledError
        await real_sleep(seconds + 0.03)  # the loop was busy and woke late

    async def quick_poll() -> None:
        return None

    monkeypatch.setattr(scheduler.asyncio, "sleep", late_sleep)
    with pytest.raises(asyncio.CancelledError):
        await Scheduler([], {})._loop(Job("refoss", 0.1, quick_poll))
    assert waits[1] == pytest.approx(0.07, abs=0.015)
