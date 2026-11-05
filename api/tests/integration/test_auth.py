from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import text

from adscontrol.app import create_app
from adscontrol.auth import MAX_ATTEMPTS, set_pin
from adscontrol.config import Settings

pytestmark = pytest.mark.integration

PIN = "482915"
START = datetime(2026, 11, 2, 16, 0, tzinfo=timezone.utc)
HEADERS = {"X-Control-Action": "1"}


class Clock:
    def __init__(self):
        self.now = START

    def __call__(self):
        return self.now


@pytest.fixture
async def clock():
    return Clock()


def _client(url, clock, *, scheme="https", insecure=False):
    app = create_app(
        Settings(database_url=url, allow_insecure_pin=insecure), jobs=[], start_jobs=False
    )
    app.state.clock = clock
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"{scheme}://t")


@pytest.fixture
async def api(session, migrated_db, clock):
    await session.execute(text("TRUNCATE auth_settings"))
    await set_pin(session, PIN)
    await session.commit()
    async with _client(migrated_db, clock) as c:
        yield c


async def _enter(api, pin=PIN):
    return await api.post("/api/auth/pin", json={"pin": pin}, headers=HEADERS)


async def test_protected_route_401_without_session(api):
    assert (await api.get("/api/auth/check")).status_code == 401


async def test_correct_pin_unlocks(api):
    assert (await _enter(api)).status_code == 200
    assert (await api.get("/api/auth/check")).status_code == 204


async def test_correct_pin_sets_cookie_flags(api):
    cookie = (await _enter(api)).headers["set-cookie"].lower()
    for flag in ("httponly", "secure", "samesite=strict", "path=/"):
        assert flag in cookie


async def test_wrong_pin_rejected_and_counted(api, session):
    assert (await _enter(api, "000000")).status_code == 401
    assert (await api.get("/api/auth/check")).status_code == 401
    assert await session.scalar(text("SELECT failures FROM auth_settings")) == 1


async def test_lockout_after_max_attempts_even_with_right_pin(api, clock):
    for _ in range(MAX_ATTEMPTS):
        await _enter(api, "000000")
    r = await _enter(api)
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) == 60
    clock.now += timedelta(seconds=61)
    assert (await _enter(api)).status_code == 200


async def test_lockout_doubles_and_success_resets_it(api, clock):
    for _ in range(MAX_ATTEMPTS):
        await _enter(api, "000000")
    clock.now += timedelta(seconds=61)
    assert (await _enter(api, "000000")).status_code == 401
    r = await _enter(api)
    assert int(r.headers["retry-after"]) == 120
    clock.now += timedelta(seconds=121)
    assert (await _enter(api)).status_code == 200
    assert (await _enter(api, "000000")).status_code == 401
    assert (await _enter(api)).status_code == 200


async def test_lockout_is_capped_at_an_hour(api, clock):
    for _ in range(MAX_ATTEMPTS + 12):
        await _enter(api, "000000")
        clock.now += timedelta(hours=2)
    await _enter(api, "000000")
    assert int((await _enter(api)).headers["retry-after"]) == 3600


async def test_lockout_survives_restart(api, migrated_db, clock):
    for _ in range(MAX_ATTEMPTS):
        await _enter(api, "000000")
    async with _client(migrated_db, clock) as fresh:
        assert (await _enter(fresh)).status_code == 429


async def test_changing_pin_revokes_sessions(api, session):
    await _enter(api)
    await set_pin(session, "771204")
    await session.commit()
    assert (await api.get("/api/auth/check")).status_code == 401
    assert (await _enter(api, PIN)).status_code == 401
    assert (await _enter(api, "771204")).status_code == 200


async def test_session_expires_after_90_days(api, clock):
    await _enter(api)
    clock.now += timedelta(days=89)
    assert (await api.get("/api/auth/check")).status_code == 204
    clock.now += timedelta(days=2)
    assert (await api.get("/api/auth/check")).status_code == 401


@pytest.mark.parametrize("cookie", ["garbage", "1.9999999999.abc", "", "a.b.c.d"])
async def test_forged_cookie_is_rejected(session, migrated_db, clock, api, cookie):
    async with _client(migrated_db, clock) as fresh:
        fresh.headers["cookie"] = f"control_session={cookie}"
        assert (await fresh.get("/api/auth/check")).status_code == 401


async def test_tampered_expiry_is_rejected(api, migrated_db, clock):
    await _enter(api)
    generation, expires, signature = api.cookies["control_session"].split(".")
    async with _client(migrated_db, clock) as fresh:
        fresh.cookies.set(
            "control_session", f"{generation}.{int(expires) + 999}.{signature}", domain="t"
        )
        assert (await fresh.get("/api/auth/check")).status_code == 401


async def test_cookie_signed_with_another_key_is_rejected(api, migrated_db, clock, session):
    await _enter(api)
    value = api.cookies["control_session"]
    await session.execute(text("UPDATE auth_settings SET signing_key = :k"), {"k": b"x" * 32})
    await session.commit()
    async with _client(migrated_db, clock) as fresh:
        fresh.headers["cookie"] = f"control_session={value}"
        assert (await fresh.get("/api/auth/check")).status_code == 401


async def test_pin_not_stored_in_plaintext(api, session):
    row = (await session.execute(text("SELECT * FROM auth_settings"))).one()
    assert PIN not in str(tuple(row))


async def test_lock_ends_this_session(api):
    await _enter(api)
    assert (await api.post("/api/auth/lock", headers=HEADERS)).status_code == 204
    assert (await api.get("/api/auth/check")).status_code == 401


async def test_pin_needs_the_action_header(api):
    assert (await api.post("/api/auth/pin", json={"pin": PIN})).status_code == 403


async def test_plain_http_is_refused(session, migrated_db, clock, api):
    async with _client(migrated_db, clock, scheme="http") as plain:
        assert (
            await plain.post("/api/auth/pin", json={"pin": PIN}, headers=HEADERS)
        ).status_code == 400
        assert (await plain.get("/api/auth/check")).status_code == 400


async def test_https_through_the_proxy_is_accepted(session, migrated_db, clock, api):
    async with _client(migrated_db, clock, scheme="http") as proxied:
        headers = {**HEADERS, "X-Forwarded-Proto": "https"}
        assert (
            await proxied.post("/api/auth/pin", json={"pin": PIN}, headers=headers)
        ).status_code == 200


async def test_insecure_override_allows_plain_http_for_development(
    session, migrated_db, clock, api
):
    async with _client(migrated_db, clock, scheme="http", insecure=True) as plain:
        r = await plain.post("/api/auth/pin", json={"pin": PIN}, headers=HEADERS)
        assert r.status_code == 200
        assert "secure" not in r.headers["set-cookie"].lower()
        assert (await plain.get("/api/auth/check")).status_code == 204


async def test_no_pin_set_refuses_everything_and_says_so(session, migrated_db, clock):
    await session.execute(text("TRUNCATE auth_settings"))
    await session.commit()
    async with _client(migrated_db, clock) as c:
        assert (await _enter(c)).status_code == 409
        assert (await c.get("/api/auth/status")).json() == {"pin_set": False, "unlocked": False}


async def test_status_reports_unlocked(api):
    assert (await api.get("/api/auth/status")).json() == {"pin_set": True, "unlocked": False}
    await _enter(api)
    assert (await api.get("/api/auth/status")).json() == {"pin_set": True, "unlocked": True}


@pytest.mark.parametrize("bad", ["123", "12345", "abcdef", "1234567890123", ""])
async def test_weak_pin_cannot_be_set(session, bad):
    with pytest.raises(ValueError):
        await set_pin(session, bad)


async def test_energy_and_maintenance_remain_open(api):
    assert (await api.get("/api/live")).status_code == 200
    assert (await api.get("/api/maintenance")).status_code == 200
    assert (await api.get("/api/energy/ranking?range=7d")).status_code == 200
    assert (await api.get("/api/bills")).status_code == 200


async def test_simultaneous_wrong_guesses_each_count(api, session):
    import asyncio

    codes = [
        r.status_code for r in await asyncio.gather(*(_enter(api, "000000") for _ in range(10)))
    ]
    assert codes.count(401) == MAX_ATTEMPTS
    assert codes.count(429) == 10 - MAX_ATTEMPTS
    assert await session.scalar(text("SELECT failures FROM auth_settings")) == MAX_ATTEMPTS


async def test_a_forwarded_https_claim_counts_only_from_caddy_on_this_mac(
    session, migrated_db, clock
):
    await session.execute(text("TRUNCATE auth_settings"))
    await set_pin(session, PIN)
    await session.commit()
    app = create_app(Settings(database_url=migrated_db), jobs=[], start_jobs=False)
    app.state.clock = clock
    claim = {**HEADERS, "X-Forwarded-Proto": "https"}
    phone = httpx.ASGITransport(app=app, client=("192.168.4.20", 50000))
    async with httpx.AsyncClient(transport=phone, base_url="http://192.168.4.41:8100") as c:
        assert (await c.post("/api/auth/pin", json={"pin": PIN}, headers=claim)).status_code == 400
    caddy = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    async with httpx.AsyncClient(transport=caddy, base_url="http://192.168.4.41") as c:
        assert (await c.post("/api/auth/pin", json={"pin": PIN}, headers=claim)).status_code == 200


async def test_requests_for_other_hostnames_are_refused(migrated_db, clock):
    """A DNS-rebinding page arrives with its own hostname; the house's addresses are the only ones served."""
    app = create_app(Settings(database_url=migrated_db), jobs=[], start_jobs=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://evil.example:8100") as c:
        assert (await c.get("/api/maintenance")).status_code == 400
    for host in ("192.168.4.41:8100", "MacBook-Air-2.local", "control.home.arpa", "localhost:8100"):
        async with httpx.AsyncClient(transport=transport, base_url=f"http://{host}") as c:
            assert (await c.get("/api/auth/status")).status_code == 200, host
