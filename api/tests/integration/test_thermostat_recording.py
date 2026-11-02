from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from adscontrol.nest.sdm import NestError, Thermostat
from adscontrol.nest.thermostat import ThermostatRecorder, list_paired, pair_thermostat

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 2, 16, 0, tzinfo=timezone.utc)


def _t(device="up", name="Upstairs", ambient=24.0) -> Thermostat:
    return Thermostat(device, name, ambient, 41, "COOL", "COOLING", 23.5, None, False, True)


class Fake:
    def __init__(self, result):
        self.result = result

    async def list_thermostats(self):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
async def clean(session):
    await session.execute(text("TRUNCATE thermostats CASCADE"))
    await session.execute(text("TRUNCATE thermostat_readings"))
    await session.commit()


def _recorder(engine, client):
    return ThermostatRecorder(client, async_sessionmaker(engine), clock=lambda: NOW)


async def test_records_a_row_for_each_thermostat(engine, session, clean):
    await _recorder(engine, Fake([_t(), _t("down", "Downstairs", None)])).poll()
    rows = (
        await session.execute(text("SELECT * FROM thermostat_readings ORDER BY ambient_c"))
    ).all()
    assert len(rows) == 2
    assert rows[0].ambient_c == 24.0
    assert rows[0].hvac_status == "COOLING"
    assert rows[1].ambient_c is None


async def test_repeat_polls_keep_one_thermostat_row(engine, session, clean):
    await _recorder(engine, Fake([_t()])).poll()
    later = ThermostatRecorder(
        Fake([_t()]), async_sessionmaker(engine), clock=lambda: NOW + timedelta(minutes=1)
    )
    await later.poll()
    assert await session.scalar(text("SELECT count(*) FROM thermostats")) == 1


async def test_failed_poll_writes_nothing(engine, session, clean):
    with pytest.raises(NestError):
        await _recorder(engine, Fake(NestError("down"))).poll()
    assert await session.scalar(text("SELECT count(*) FROM thermostat_readings")) == 0


async def test_pairing_with_a_zone(engine, session, clean):
    await _recorder(engine, Fake([_t()])).poll()
    await pair_thermostat(session, "Upstairs", "Upstairs A/C")
    await session.commit()
    paired = await list_paired(session)
    assert paired[0].zone_name == "Upstairs A/C"


async def test_pairing_unknown_names_is_an_error(engine, session, clean):
    await _recorder(engine, Fake([_t()])).poll()
    with pytest.raises(ValueError):
        await pair_thermostat(session, "Attic", "Upstairs A/C")
    with pytest.raises(ValueError):
        await pair_thermostat(session, "Upstairs", "Garage")


async def test_google_down_degrades_only_nest_source(engine, session, clean):
    from adscontrol.scheduler import Job, Scheduler, SourceState

    states: dict[str, SourceState] = {}
    ok = await Scheduler([], states).run_once(
        Job("nest", 60, _recorder(engine, Fake(NestError("down"))).poll)
    )
    assert ok is False
    assert "down" in states["nest"].last_error
