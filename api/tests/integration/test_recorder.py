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


def _recorder(engine, client, discovered=None, uuid_path=None, used=None):
    discovered = [] if discovered is None else discovered
    used = [] if used is None else used

    async def discover(host):
        discovered.append(host)
        return "uuid"

    def make_client(host, uuid):
        used.append(uuid)
        return client

    return Recorder(
        "host",
        async_sessionmaker(engine),
        discover=discover,
        make_client=make_client,
        uuid_path=uuid_path,
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


async def test_a_read_error_reuses_the_remembered_uuid(engine, tmp_path):
    """Discovery is a Wi-Fi broadcast the monitor often misses; a read error must not depend on it."""
    client = _Client(RefossError("closed"))
    discovered: list[str] = []
    recorder = _recorder(engine, client, discovered, uuid_path=tmp_path / "refoss_uuid")
    with pytest.raises(RefossError):
        await recorder.poll()
    client.result = _readings()
    await recorder.poll()
    assert discovered == ["host"]


async def test_a_remembered_uuid_skips_discovery(engine, tmp_path):
    (tmp_path / "refoss_uuid").write_text("abc\n")
    discovered: list[str] = []
    used: list[str] = []
    await _recorder(engine, _Client(_readings()), discovered, tmp_path / "refoss_uuid", used).poll()
    assert discovered == []
    assert used == ["abc"]


async def test_a_discovered_uuid_is_remembered(engine, tmp_path):
    await _recorder(engine, _Client(_readings()), uuid_path=tmp_path / "refoss_uuid").poll()
    assert (tmp_path / "refoss_uuid").read_text().strip() == "uuid"


async def test_uuid_is_kept_between_good_polls(engine):
    discovered: list[str] = []
    recorder = _recorder(engine, _Client(_readings()), discovered)
    await recorder.poll()
    await recorder.poll()
    assert discovered == ["host"]
