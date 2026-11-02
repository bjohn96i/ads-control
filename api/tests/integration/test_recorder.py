import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from adscontrol.refoss.client import ChannelReading, RefossError
from adscontrol.refoss.recorder import Recorder
from adscontrol.scheduler import Job, Scheduler, SourceState

pytestmark = pytest.mark.integration


def _readings() -> list[ChannelReading]:
    return [ChannelReading(c, 100.0, 120.0, 1.0, 0.9, 5) for c in range(1, 19)]


class _Client:
    def __init__(self, result):
        self.result = result

    async def read_channels(self):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _recorder(engine, client, discovered=None):
    discovered = [] if discovered is None else discovered

    async def discover(host):
        discovered.append(host)
        return "uuid"

    return Recorder(
        "host",
        async_sessionmaker(engine),
        discover=discover,
        make_client=lambda host, uuid: client,
    )


async def _count(session) -> int:
    return await session.scalar(text("SELECT count(*) FROM channel_readings"))


async def test_recorder_writes_18_rows_per_poll(engine, session):
    await _recorder(engine, _Client(_readings())).poll()
    assert await _count(session) == 18


async def test_failed_poll_writes_nothing_and_marks_source_failed(engine, session):
    recorder = _recorder(engine, _Client(RefossError("closed")))
    states: dict[str, SourceState] = {}
    ok = await Scheduler([], states).run_once(Job("refoss", 10, recorder.poll))
    assert ok is False
    assert "closed" in states["refoss"].last_error
    assert await _count(session) == 0


async def test_rediscovers_uuid_after_refoss_error(engine):
    client = _Client(RefossError("closed"))
    discovered: list[str] = []
    recorder = _recorder(engine, client, discovered)
    with pytest.raises(RefossError):
        await recorder.poll()
    client.result = _readings()
    await recorder.poll()
    assert discovered == ["host", "host"]


async def test_uuid_is_kept_between_good_polls(engine):
    discovered: list[str] = []
    recorder = _recorder(engine, _Client(_readings()), discovered)
    await recorder.poll()
    await recorder.poll()
    assert discovered == ["host"]
