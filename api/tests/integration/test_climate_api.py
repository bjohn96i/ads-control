from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import text

from adscontrol.app import create_app
from adscontrol.auth import COOKIE_NAME, load, make_session_value, set_pin
from adscontrol.config import Settings
from adscontrol.nest.sdm import NestError, RateLimited, Thermostat

pytestmark = pytest.mark.integration

JULY = datetime(2026, 7, 15, 19, 0, tzinfo=timezone.utc)  # 3 PM Eastern: on-peak
OCT = datetime(2026, 10, 15, 19, 0, tzinfo=timezone.utc)
HEADERS = {"X-Control-Action": "1"}


class FakeSdm:
    def __init__(self, mode="COOL", eco=False, online=True, error=None):
        self.mode, self.eco, self.online, self.error = mode, eco, online, error
        self.sets = []

    async def list_thermostats(self):
        return [
            Thermostat(
                "up", "Upstairs", 24.0, 40, self.mode, "COOLING", 23.0, 19.0, self.eco, self.online
            )
        ]

    async def set_setpoint(self, device_id, mode, *, cool_c=None, heat_c=None):
        if self.error:
            raise self.error
        self.sets.append((device_id, mode, cool_c, heat_c))


@pytest.fixture
async def seeded(session):
    await session.execute(text("TRUNCATE thermostats CASCADE"))
    await session.execute(text("TRUNCATE thermostat_readings"))
    await session.execute(text("TRUNCATE outdoor_readings"))
    await session.execute(text("TRUNCATE auth_settings"))
    await session.execute(text("UPDATE zones SET multiplier = 1"))
    await session.execute(
        text(
            "INSERT INTO thermostats (device_id, name, zone_id) SELECT 'up', 'Upstairs', id FROM zones WHERE name = 'Upstairs A/C'"
        )
    )
    await set_pin(session, "482915")
    await session.commit()
    return await session.scalar(text("SELECT id FROM thermostats"))


async def _reading(
    session, thermostat_id, at, *, ambient=24.0, status="COOLING", mode="COOL", heat=None, cool=23.0
):
    await session.execute(
        text(
            "INSERT INTO thermostat_readings VALUES (:t, :i, :a, 40, :h, :c, :m, :s, false, true)"
        ),
        dict(t=at, i=thermostat_id, a=ambient, h=heat, c=cool, m=mode, s=status),
    )
    await session.commit()


async def _ac(session, start, end, watts):
    await session.execute(
        text(
            """
            INSERT INTO channel_readings SELECT t, 18, :w, 120, 1, 1, 0 FROM generate_series(
                CAST(:s AS timestamptz), CAST(:e AS timestamptz) - INTERVAL '10 seconds', INTERVAL '10 seconds') t
            """
        ),
        dict(w=watts, s=start, e=end),
    )
    await session.commit()


async def _client(session, url, now, sdm=None, *, unlocked=True):
    app = create_app(Settings(database_url=url), jobs=[], start_jobs=False)
    app.state.clock = lambda: now
    app.state.sdm = sdm or FakeSdm()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://t")
    if unlocked:
        client.headers["cookie"] = f"{COOKIE_NAME}={make_session_value(await load(session), now)}"
    return client


async def _set(client, thermostat_id, **body):
    return await client.post(f"/api/climate/{thermostat_id}/setpoint", json=body, headers=HEADERS)


async def test_setpoint_requires_pin(session, migrated_db, seeded):
    sdm = FakeSdm()
    async with await _client(session, migrated_db, OCT, sdm, unlocked=False) as c:
        assert (await _set(c, seeded, temp_f=70)).status_code == 401
    assert sdm.sets == []


async def test_setpoint_requires_the_action_header(session, migrated_db, seeded):
    async with await _client(session, migrated_db, OCT) as c:
        r = await c.post(f"/api/climate/{seeded}/setpoint", json={"temp_f": 70})
        assert r.status_code == 403


async def test_setpoint_sets_cool_in_celsius(session, migrated_db, seeded):
    sdm = FakeSdm()
    async with await _client(session, migrated_db, OCT, sdm) as c:
        assert (await _set(c, seeded, temp_f=72)).status_code == 200
    device, mode, cool_c, heat_c = sdm.sets[0]
    assert (device, mode, heat_c) == ("up", "COOL", None)
    assert cool_c == pytest.approx(22.222, abs=0.001)


async def test_setpoint_in_heat_mode_sets_heat(session, migrated_db, seeded):
    sdm = FakeSdm(mode="HEAT")
    async with await _client(session, migrated_db, OCT, sdm) as c:
        await _set(c, seeded, temp_f=68)
    assert sdm.sets[0][1:3] == ("HEAT", None)
    assert sdm.sets[0][3] == pytest.approx(20.0)


async def test_range_mode_moves_the_chosen_end_only(session, migrated_db, seeded):
    sdm = FakeSdm(mode="HEATCOOL")
    async with await _client(session, migrated_db, OCT, sdm) as c:
        assert (await _set(c, seeded, temp_f=72)).status_code == 422
        assert (await _set(c, seeded, temp_f=72, target="cool")).status_code == 200
    assert sdm.sets[0][2] == pytest.approx(22.222, abs=0.001)
    assert sdm.sets[0][3] == pytest.approx(19.0)


@pytest.mark.parametrize("temp", [49, 91])
async def test_out_of_range_setpoint_rejected(session, migrated_db, seeded, temp):
    sdm = FakeSdm()
    async with await _client(session, migrated_db, OCT, sdm) as c:
        assert (await _set(c, seeded, temp_f=temp)).status_code == 422
    assert sdm.sets == []


@pytest.mark.parametrize(
    "sdm",
    [FakeSdm(mode="OFF"), FakeSdm(eco=True), FakeSdm(online=False)],
    ids=["off", "eco", "offline"],
)
async def test_states_that_cannot_take_a_setpoint_are_409(session, migrated_db, seeded, sdm):
    async with await _client(session, migrated_db, OCT, sdm) as c:
        r = await _set(c, seeded, temp_f=70)
        assert r.status_code == 409
        assert r.json()["detail"]
    assert sdm.sets == []


async def test_unknown_thermostat_is_404(session, migrated_db, seeded):
    async with await _client(session, migrated_db, OCT) as c:
        assert (await _set(c, 999999, temp_f=70)).status_code == 404


@pytest.mark.parametrize(
    ("error", "status"),
    [(NestError("down"), 502), (RateLimited("slow"), 503)],
    ids=["down", "limited"],
)
async def test_google_failure_is_reported_not_hidden(session, migrated_db, seeded, error, status):
    async with await _client(session, migrated_db, OCT, FakeSdm(error=error)) as c:
        assert (await _set(c, seeded, temp_f=70)).status_code == status


async def test_no_background_setpoint_calls(session, migrated_db, seeded):
    sdm = FakeSdm()
    await _reading(session, seeded, OCT)
    async with await _client(session, migrated_db, OCT, sdm) as c:
        await c.get("/api/climate?range=1d")
        await c.get("/api/climate/summary")
        await c.get("/api/live")
    assert sdm.sets == []


async def test_reading_climate_needs_no_pin(session, migrated_db, seeded):
    await _reading(session, seeded, OCT)
    async with await _client(session, migrated_db, OCT, unlocked=False) as c:
        assert (await c.get("/api/climate?range=1d")).status_code == 200
        assert (await c.get("/api/climate/summary")).status_code == 200


async def test_summary_reports_fahrenheit_and_status(session, migrated_db, seeded):
    await _reading(
        session, seeded, OCT, ambient=20.0, status="HEATING", mode="HEAT", heat=21.0, cool=None
    )
    async with await _client(session, migrated_db, OCT) as c:
        t = (await c.get("/api/climate/summary")).json()["thermostats"][0]
    assert t["name"] == "Upstairs"
    assert t["ambient_f"] == pytest.approx(68.0)
    assert t["setpoint_f"] == pytest.approx(69.8)
    assert (t["mode"], t["hvac_status"], t["stale"]) == ("HEAT", "HEATING", False)


async def test_old_reading_is_stale_with_no_temperature(session, migrated_db, seeded):
    await _reading(session, seeded, OCT - timedelta(minutes=6))
    async with await _client(session, migrated_db, OCT) as c:
        t = (await c.get("/api/climate/summary")).json()["thermostats"][0]
    assert t["stale"] is True
    assert t["ambient_f"] is None


async def test_timeline_lines_up_temperature_running_and_power(session, migrated_db, seeded):
    start = OCT - timedelta(minutes=30)
    await _ac(session, start, OCT, 1000.0)
    for m in range(0, 30, 5):
        await _reading(session, seeded, start + timedelta(minutes=m))
    await session.execute(text("UPDATE zones SET multiplier = 2 WHERE name = 'Upstairs A/C'"))
    await session.execute(text("INSERT INTO outdoor_readings VALUES (:t, 30.0)"), {"t": start})
    await session.commit()
    async with await _client(session, migrated_db, OCT) as c:
        timeline = (await c.get("/api/climate?range=1d")).json()["thermostats"][0]["timeline"]
    point = next(p for p in timeline if p["ambient_f"] is not None)
    assert point["ambient_f"] == pytest.approx(75.2)
    assert point["setpoint_f"] == pytest.approx(73.4)
    assert point["running"] is True
    assert point["ac_watts"] == pytest.approx(2000)
    assert point["outdoor_f"] == pytest.approx(86.0)


async def test_timeline_gaps_stay_null(session, migrated_db, seeded):
    await _reading(session, seeded, OCT - timedelta(hours=2))
    async with await _client(session, migrated_db, OCT) as c:
        timeline = (await c.get("/api/climate?range=1d")).json()["thermostats"][0]["timeline"]
    assert any(p["ambient_f"] is None and p["ac_watts"] is None for p in timeline)


async def test_on_peak_flag_only_in_on_peak_period(session, migrated_db, seeded):
    await _ac(session, JULY - timedelta(hours=1), JULY, 800.0)
    await _reading(session, seeded, JULY)
    async with await _client(session, migrated_db, JULY) as c:
        assert (await c.get("/api/climate?range=1d")).json()["thermostats"][0][
            "on_peak_flag"
        ] is True
    night = datetime(2026, 7, 16, 7, 0, tzinfo=timezone.utc)
    await _ac(session, night - timedelta(hours=1), night, 800.0)
    await _reading(session, seeded, night)
    async with await _client(session, migrated_db, night) as c:
        assert (await c.get("/api/climate?range=1d")).json()["thermostats"][0][
            "on_peak_flag"
        ] is False


async def test_on_peak_flag_needs_real_load(session, migrated_db, seeded):
    await _ac(session, JULY - timedelta(hours=1), JULY, 100.0)
    await _reading(session, seeded, JULY)
    async with await _client(session, migrated_db, JULY) as c:
        assert (await c.get("/api/climate?range=1d")).json()["thermostats"][0][
            "on_peak_flag"
        ] is False


async def test_unknown_range_is_422(session, migrated_db, seeded):
    async with await _client(session, migrated_db, OCT) as c:
        assert (await c.get("/api/climate?range=forever")).status_code == 422


async def test_no_estimate_yet_says_none(session, migrated_db, seeded):
    await _reading(session, seeded, OCT)
    async with await _client(session, migrated_db, OCT) as c:
        assert (await c.get("/api/climate?range=1d")).json()["thermostats"][0]["estimate"] is None


async def test_weather_poll_stores_and_sends_only_rounded_location(session, migrated_db, seeded):
    import respx
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from adscontrol.weather import WeatherRecorder

    engine = create_async_engine(migrated_db)
    with respx.mock as router:
        route = router.get(url__startswith="https://api.open-meteo.com/").mock(
            return_value=httpx.Response(
                200, json={"current": {"temperature_2m": 12.5, "weather_code": 61, "is_day": 0}}
            )
        )
        await WeatherRecorder(
            33.749, -84.388, async_sessionmaker(engine), clock=lambda: OCT
        ).poll()
    await engine.dispose()
    assert route.calls[0].request.url.params["latitude"] == "33.75"
    assert route.calls[0].request.url.params["longitude"] == "-84.3"
    assert await session.scalar(text("SELECT temp_c FROM outdoor_readings")) == 12.5
    assert route.calls[0].request.url.params["current"] == "temperature_2m,weather_code,is_day"
    row = (await session.execute(text("SELECT weather_code, is_day FROM outdoor_readings"))).one()
    assert (row.weather_code, row.is_day) == (61, False)
