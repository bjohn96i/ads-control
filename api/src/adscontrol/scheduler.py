"""Runs each job on its interval; failures are recorded per source, never fatal."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

log = logging.getLogger(__name__)


@dataclass
class Job:
    name: str
    interval_s: float
    poll: Callable[[], Awaitable[None]]


@dataclass
class SourceState:
    interval_s: float
    last_success: datetime | None = None
    last_error: str | None = None

    def healthy(self, now: datetime) -> bool:
        if self.last_success is None:
            return False
        return (now - self.last_success).total_seconds() <= 3 * self.interval_s


class Scheduler:
    def __init__(self, jobs: list[Job], states: dict[str, SourceState]) -> None:
        self._jobs = jobs
        self._states = states
        self._tasks: list[asyncio.Task] = []

    async def run_once(self, job: Job) -> bool:
        state = self._states.setdefault(job.name, SourceState(job.interval_s))
        try:
            await job.poll()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one source failing must not kill the loop
            state.last_error = f"{type(exc).__name__}: {exc}"
            log.warning("source %s failed: %s", job.name, state.last_error)
            return False
        state.last_success = datetime.now(timezone.utc)
        state.last_error = None
        return True

    async def _loop(self, job: Job) -> None:
        # Energy maths counts each sample as one interval, so polls keep to a fixed timetable:
        # the poll's own time and any late wake-up come out of the next wait instead of adding up.
        loop = asyncio.get_running_loop()
        due = loop.time()
        while True:
            await self.run_once(job)
            # A poll that overran a whole interval starts the timetable again rather than bursting.
            due = max(due + job.interval_s, loop.time())
            await asyncio.sleep(due - loop.time())

    async def start(self) -> None:
        self._tasks = [asyncio.create_task(self._loop(j), name=j.name) for j in self._jobs]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
