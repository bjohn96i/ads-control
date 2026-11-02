import base64
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
    assert public == {
        "list_thermostats",
        "set_setpoint",
        "list_cameras",
        "generate_stream",
        "stop_stream",
        "fetch_event_image",
        "pull_events",
        "ack_events",
    }


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
    assert query["scope"] == [
        "https://www.googleapis.com/auth/sdm.service https://www.googleapis.com/auth/pubsub"
    ]
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


DOORBELL = {
    "name": f"enterprises/{PROJECT}/devices/door1",
    "type": "sdm.devices.types.DOORBELL",
    "traits": {
        "sdm.devices.traits.Info": {"customName": "Entryway doorbell"},
        "sdm.devices.traits.CameraLiveStream": {"supportedProtocols": ["WEB_RTC"]},
    },
}
DISPLAY = {
    "name": f"enterprises/{PROJECT}/devices/hub1",
    "type": "sdm.devices.types.DISPLAY",
    "traits": {
        "sdm.devices.traits.Info": {"customName": ""},
        "sdm.devices.traits.CameraLiveStream": {"supportedProtocols": ["WEB_RTC"]},
    },
    "parentRelations": [{"displayName": "Living Room"}],
}
NO_CAMERA_DISPLAY = {
    "name": "enterprises/p/devices/hub2",
    "type": "sdm.devices.types.DISPLAY",
    "traits": {},
}


@respx.mock
async def test_lists_cameras_with_their_kind(tmp_path):
    _token()
    respx.get(f"{BASE}/devices").mock(
        return_value=httpx.Response(
            200, json={"devices": [THERMOSTAT, DOORBELL, DISPLAY, NO_CAMERA_DISPLAY]}
        )
    )
    cameras = await _client(tmp_path).list_cameras()
    assert [(c.device_id, c.name, c.kind) for c in cameras] == [
        ("door1", "Entryway doorbell", "doorbell"),
        ("hub1", "Living Room", "display"),
    ]


@respx.mock
async def test_generate_stream_sends_the_offer_and_returns_the_answer(tmp_path):
    _token()
    route = respx.post(f"{BASE}/devices/door1:executeCommand").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": {
                    "answerSdp": "v=0",
                    "expiresAt": "2026-11-02T16:05:00Z",
                    "mediaSessionId": "s1",
                }
            },
        )
    )
    result = await _client(tmp_path).generate_stream("door1", "offer")
    body = json.loads(route.calls[0].request.content)
    assert body == {
        "command": "sdm.devices.commands.CameraLiveStream.GenerateWebRtcStream",
        "params": {"offerSdp": "offer"},
    }
    assert result == {
        "answer_sdp": "v=0",
        "expires_at": "2026-11-02T16:05:00Z",
        "media_session_id": "s1",
    }


@respx.mock
async def test_stop_stream_names_the_session(tmp_path):
    _token()
    route = respx.post(f"{BASE}/devices/door1:executeCommand").mock(
        return_value=httpx.Response(200, json={})
    )
    await _client(tmp_path).stop_stream("door1", "s1")
    body = json.loads(route.calls[0].request.content)
    assert body["command"].endswith("StopWebRtcStream")
    assert body["params"] == {"mediaSessionId": "s1"}


@respx.mock
async def test_event_image_downloads_with_basic_token(tmp_path):
    _token()
    respx.post(f"{BASE}/devices/door1:executeCommand").mock(
        return_value=httpx.Response(
            200, json={"results": {"url": "https://img.example/x", "token": "g.0.tok"}}
        )
    )
    image = respx.get("https://img.example/x").mock(
        return_value=httpx.Response(200, content=b"jpegbytes")
    )
    assert await _client(tmp_path).fetch_event_image("door1", "e1") == b"jpegbytes"
    request = image.calls[0].request
    assert request.headers["authorization"] == "Basic g.0.tok"
    assert request.url.params["width"] == "960"


@respx.mock
async def test_expired_event_image_is_a_nest_error(tmp_path):
    _token()
    respx.post(f"{BASE}/devices/door1:executeCommand").mock(
        return_value=httpx.Response(400, json={"error": {"message": "no longer available"}})
    )
    with pytest.raises(NestError):
        await _client(tmp_path).fetch_event_image("door1", "e1")


@respx.mock
async def test_failed_image_download_is_a_nest_error(tmp_path):
    _token()
    respx.post(f"{BASE}/devices/door1:executeCommand").mock(
        return_value=httpx.Response(
            200, json={"results": {"url": "https://img.example/x", "token": "t"}}
        )
    )
    respx.get("https://img.example/x").mock(return_value=httpx.Response(410))
    with pytest.raises(NestError):
        await _client(tmp_path).fetch_event_image("door1", "e1")


SUBSCRIPTION = "projects/p/subscriptions/s"
PUBSUB = f"https://pubsub.googleapis.com/v1/{SUBSCRIPTION}"


@respx.mock
async def test_pull_decodes_messages_and_tolerates_bad_ones(tmp_path):
    _token()
    good = base64.b64encode(json.dumps({"eventId": "x"}).encode()).decode()
    respx.post(f"{PUBSUB}:pull").mock(
        return_value=httpx.Response(
            200,
            json={
                "receivedMessages": [
                    {"ackId": "a1", "message": {"data": good}},
                    {"ackId": "a2", "message": {"data": "!!!notbase64"}},
                    {"ackId": "a3", "message": {}},
                ]
            },
        )
    )
    assert await _client(tmp_path).pull_events(SUBSCRIPTION) == [
        ("a1", {"eventId": "x"}),
        ("a2", None),
        ("a3", None),
    ]


@respx.mock
async def test_pull_with_nothing_waiting_is_empty(tmp_path):
    _token()
    respx.post(f"{PUBSUB}:pull").mock(return_value=httpx.Response(200, json={}))
    assert await _client(tmp_path).pull_events(SUBSCRIPTION) == []


@respx.mock
async def test_ack_sends_ids(tmp_path):
    _token()
    route = respx.post(f"{PUBSUB}:acknowledge").mock(return_value=httpx.Response(200, json={}))
    await _client(tmp_path).ack_events(SUBSCRIPTION, ["a1", "a2"])
    assert json.loads(route.calls[0].request.content) == {"ackIds": ["a1", "a2"]}
