import pytest
from sqlalchemy import text

from adscontrol.zones import Zone, list_zones, zone_power

pytestmark = pytest.mark.integration


async def test_seed_creates_expected_zones(session):
    zones = await list_zones(session)
    circuits = [z for z in zones if z.kind == "circuit"]
    assert len(circuits) == 12
    assert [z.channels for z in zones if z.kind == "incoming"] == [[1, 7]]
    used = {c for z in zones for c in z.channels}
    assert used.isdisjoint({4, 13, 16})
    assert used == set(range(1, 19)) - {4, 13, 16}


async def test_ac_zones_are_seasonal(session):
    seasonal = {z.name for z in await list_zones(session) if z.seasonal}
    assert seasonal == {"Downstairs A/C", "Upstairs A/C"}


async def test_dryer_sums_two_channels(session):
    dryer = next(z for z in await list_zones(session) if z.name == "Dryer")
    assert dryer.channels == [5, 11]
    assert zone_power(dryer, {5: 2000.0, 11: 2100.0}) == 4100.0


async def test_hypertable_and_aggregates_exist(session):
    hyper = await session.scalar(
        text(
            "SELECT count(*) FROM timescaledb_information.hypertables WHERE hypertable_name = 'channel_readings'"
        )
    )
    aggregates = await session.scalars(
        text("SELECT view_name FROM timescaledb_information.continuous_aggregates")
    )
    assert hyper == 1
    assert set(aggregates) == {"channel_hourly", "channel_daily"}


async def test_retention_and_compression_policies_exist(session):
    procs = await session.scalars(
        text(
            "SELECT proc_name FROM timescaledb_information.jobs WHERE hypertable_name = 'channel_readings'"
        )
    )
    assert {"policy_retention", "policy_compression"} <= set(procs)


def _zone(**kw) -> Zone:
    base = dict(
        id=1,
        name="X",
        channels=[2],
        multiplier=1.0,
        kind="circuit",
        pin_x=0,
        pin_y=0,
        seasonal=False,
    )
    return Zone(**{**base, **kw})


def test_multiplier_applies():
    assert zone_power(_zone(multiplier=2.0), {2: 100.0}) == 200.0


def test_zone_power_none_when_channel_missing():
    assert zone_power(_zone(channels=[5, 11]), {5: 100.0}) is None


async def test_kitchen_circuits_share_a_room(session):
    kitchen = [
        z
        for z in await list_zones(session)
        if z.name in {"Fridge/Stove", "Dishwasher", "Microwave/Sink Light"}
    ]
    assert len(kitchen) == 3
    assert {(z.room, z.floor, z.pin_x, z.pin_y) for z in kitchen} == {
        ("Kitchen", "1st floor", 33, 35)
    }


async def test_bedrooms_are_not_swapped(session):
    pins = {z.name: z.pin_x for z in await list_zones(session)}
    assert pins["Primary Bedroom"] == 37
    assert pins["Guest Bedroom (Upstairs)"] == 66
