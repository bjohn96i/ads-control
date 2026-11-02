import inspect
import json
import stat
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from adscontrol.nest.sdm import (
    TOKEN_URL,
    NestError,
    RateLimited,
    SdmClient,
    authorization_url,
    code_from_pasted,
    exchange_code,
)

PROJECT = "project-uuid"
BASE = f"https://smartdevicemanagement.googleapis.com/v1/enterprises/{PROJECT}"
DEVICE = f"enterprises/{PROJECT}/devices/abc123"
THERMOSTAT = {
    "name": DEVICE,
    "type": "sdm.devices.types.THERMOSTAT",
    "traits": {
        "sdm.devices.traits.Info": {"customName": ""},
        "sdm.devices.traits.Humidity": {"ambientHumidityPercent": 41},
        "sdm.devices.traits.Connectivity": {"status": "ONLINE"},
        "sdm.devices.traits.ThermostatMode": {
            "mode": "COOL",
            "availableModes": ["HEAT", "COOL", "HEATCOOL", "OFF"],
        },
        "sdm.devices.traits.ThermostatEco": {"mode": "OFF"},
        "sdm.devices.traits.ThermostatHvac": {"status": "COOLING"},
        "sdm.devices.traits.ThermostatTemperatureSetpoint": {"coolCelsius": 23.5},
        "sdm.devices.traits.Temperature": {"ambientTemperatureCelsius": 24.25},
    },
    "parentRelations": [{"parent": "x", "displayName": "Upstairs"}],
}
CAMERA = {"name": "enterprises/p/devices/cam", "type": "sdm.devices.types.CAMERA", "traits": {}}


def _client(tmp_path, token="refresh-token"):
    path = tmp_path / "token"
    if token:
        path.write_text(token)
    return SdmClient("client-id", "client-secret", PROJECT, path)


def _token(access="access-1"):
    return respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": access, "expires_in": 3599})
    )


@respx.mock
async def test_parses_thermostat_traits(tmp_path):
    _token()
    respx.get(f"{BASE}/devices").mock(
        return_value=httpx.Response(200, json={"devices": [THERMOSTAT, CAMERA]})
    )
    devices = await _client(tmp_path).list_thermostats()
    assert len(devices) == 1
    t = devices[0]
    assert t.device_id == "abc123"
    assert t.name == "Upstairs"
    assert (t.ambient_c, t.humidity, t.mode, t.hvac_status) == (24.25, 41, "COOL", "COOLING")
    assert (t.cool_c, t.heat_c, t.eco, t.online) == (23.5, None, False, True)


@respx.mock
async def test_custom_name_wins_over_the_room(tmp_path):
    _token()
    named = json.loads(json.dumps(THERMOSTAT))
    named["traits"]["sdm.devices.traits.Info"]["customName"] = "Hallway"
    respx.get(f"{BASE}/devices").mock(return_value=httpx.Response(200, json={"devices": [named]}))
    assert (await _client(tmp_path).list_thermostats())[0].name == "Hallway"


@respx.mock
async def test_missing_traits_are_none_not_a_crash(tmp_path):
    _token()
    bare = {"name": DEVICE, "type": THERMOSTAT["type"], "traits": {}}
    respx.get(f"{BASE}/devices").mock(return_value=httpx.Response(200, json={"devices": [bare]}))
    t = (await _client(tmp_path).list_thermostats())[0]
    assert (t.ambient_c, t.mode, t.hvac_status) == (None, None, None)


@respx.mock
async def test_no_devices_key_is_an_empty_list(tmp_path):
    _token()
    respx.get(f"{BASE}/devices").mock(return_value=httpx.Response(200, json={}))
    assert await _client(tmp_path).list_thermostats() == []


@respx.mock
async def test_set_cool_sends_only_setpoint_command(tmp_path):
    _token()
    route = respx.post(f"{BASE}/devices/abc123:executeCommand").mock(
        return_value=httpx.Response(200, json={})
    )
    await _client(tmp_path).set_setpoint("abc123", "COOL", cool_c=22.0)
    body = json.loads(route.calls[0].request.content)
    assert body == {
        "command": "sdm.devices.commands.ThermostatTemperatureSetpoint.SetCool",
        "params": {"coolCelsius": 22.0},
    }


@respx.mock
@pytest.mark.parametrize(
    ("mode", "args", "command", "params"),
    [
        ("HEAT", {"heat_c": 20.0}, "SetHeat", {"heatCelsius": 20.0}),
        (
            "HEATCOOL",
            {"heat_c": 19.0, "cool_c": 24.0},
            "SetRange",
            {"heatCelsius": 19.0, "coolCelsius": 24.0},
        ),
    ],
)
async def test_other_modes_choose_the_matching_command(tmp_path, mode, args, command, params):
    _token()
    route = respx.post(f"{BASE}/devices/abc123:executeCommand").mock(
        return_value=httpx.Response(200, json={})
    )
    await _client(tmp_path).set_setpoint("abc123", mode, **args)
    body = json.loads(route.calls[0].request.content)
    assert body["command"].endswith(command)
    assert body["params"] == params


@pytest.mark.parametrize(
    ("mode", "args"),
    [
        ("OFF", {"cool_c": 22.0}),
        ("COOL", {"heat_c": 22.0}),
        ("HEAT", {"cool_c": 22.0}),
        ("HEATCOOL", {"cool_c": 22.0}),
    ],
)
async def test_setpoint_that_cannot_apply_is_refused_without_a_call(tmp_path, mode, args):
    with respx.mock(assert_all_called=False) as router:
        with pytest.raises(NestError):
            await _client(tmp_path).set_setpoint("abc123", mode, **args)
        assert router.calls.call_count == 0


def test_client_has_no_schedule_method():
    public = {
        n for n, _ in inspect.getmembers(SdmClient, inspect.isfunction) if not n.startswith("_")
    }
    assert public == {"list_thermostats", "set_setpoint"}


@respx.mock
async def test_refreshes_expired_token_once(tmp_path):
    token = _token()
    route = respx.get(f"{BASE}/devices").mock(
        side_effect=[httpx.Response(401, json={}), httpx.Response(200, json={"devices": []})]
    )
    assert await _client(tmp_path).list_thermostats() == []
    assert token.call_count == 2
    assert route.call_count == 2


@respx.mock
async def test_second_401_gives_up(tmp_path):
    token = _token()
    respx.get(f"{BASE}/devices").mock(return_value=httpx.Response(401, json={}))
    with pytest.raises(NestError):
        await _client(tmp_path).list_thermostats()
    assert token.call_count == 2


@respx.mock
async def test_access_token_is_reused_while_valid(tmp_path):
    token = _token()
    respx.get(f"{BASE}/devices").mock(return_value=httpx.Response(200, json={}))
    client = _client(tmp_path)
    await client.list_thermostats()
    await client.list_thermostats()
    assert token.call_count == 1


@respx.mock
async def test_rate_limited_response_is_its_own_error(tmp_path):
    _token()
    respx.get(f"{BASE}/devices").mock(return_value=httpx.Response(429, json={}))
    with pytest.raises(RateLimited):
        await _client(tmp_path).list_thermostats()


@respx.mock
async def test_revoked_login_tells_you_to_log_in_again(tmp_path):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(NestError, match="nest login"):
        await _client(tmp_path).list_thermostats()


async def test_not_logged_in_tells_you_to_log_in(tmp_path):
    with pytest.raises(NestError, match="nest login"):
        await _client(tmp_path, token=None).list_thermostats()


@respx.mock
async def test_eco_mode_refusal_is_explained(tmp_path):
    _token()
    respx.post(f"{BASE}/devices/abc123:executeCommand").mock(
        return_value=httpx.Response(400, json={"error": {"message": "Thermostat is in eco mode"}})
    )
    with pytest.raises(NestError, match="eco"):
        await _client(tmp_path).set_setpoint("abc123", "COOL", cool_c=22.0)


@respx.mock
async def test_errors_never_contain_secrets(tmp_path):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(500, text="client-secret refresh-token"))
    with pytest.raises(NestError) as caught:
        await _client(tmp_path).list_thermostats()
    assert "client-secret" not in str(caught.value)
    assert "refresh-token" not in str(caught.value)


@respx.mock
async def test_network_failure_is_a_nest_error(tmp_path):
    _token()
    respx.get(f"{BASE}/devices").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(NestError):
        await _client(tmp_path).list_thermostats()


def test_authorization_url_uses_partner_connections():
    url = urlparse(authorization_url(PROJECT, "client-id"))
    query = parse_qs(url.query)
    assert url.netloc == "nestservices.google.com"
    assert PROJECT in url.path
    assert query["redirect_uri"] == ["https://www.google.com"]
    assert query["scope"] == ["https://www.googleapis.com/auth/sdm.service"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]


def test_code_from_pasted_accepts_url_or_bare_code():
    assert code_from_pasted("https://www.google.com?code=4/abc&scope=x") == "4/abc"
    assert code_from_pasted("  4/abc  ") == "4/abc"


@respx.mock
async def test_exchange_saves_refresh_token_privately(tmp_path):
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"refresh_token": "r1", "access_token": "a1"})
    )
    path = tmp_path / "token"
    await exchange_code("client-id", "client-secret", "4/abc", path)
    assert path.read_text() == "r1"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@respx.mock
async def test_exchange_without_refresh_token_fails_clearly(tmp_path):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "a1"}))
    with pytest.raises(NestError):
        await exchange_code("client-id", "client-secret", "4/abc", tmp_path / "token")
