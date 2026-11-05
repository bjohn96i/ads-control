import hashlib
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx

from adscontrol.refoss.client import READ_NAMESPACES, ChannelReading, RefossClient, RefossError

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "refoss_electricity.json").read_text()
)
URL = "http://192.168.4.254/public"
UUID = "device-uuid"


def _echo(channels):
    """Answer the way the device does: same messageId, method GETACK."""

    def handler(request: httpx.Request) -> httpx.Response:
        header = json.loads(request.content)["header"]
        return httpx.Response(
            200,
            json={
                "header": {"messageId": header["messageId"], "method": "GETACK"},
                "payload": {"electricity": channels},
            },
        )

    return handler


def _client() -> RefossClient:
    return RefossClient("192.168.4.254", UUID)


@respx.mock
async def test_units_convert_from_milli():
    respx.post(URL).mock(side_effect=_echo(FIXTURE))
    first = (await _client().read_channels())[0]
    assert first == ChannelReading(
        channel=1,
        power_w=pytest.approx(1653.078),
        voltage_v=pytest.approx(121.743),
        current_a=pytest.approx(13.64),
        power_factor=pytest.approx(0.99546, abs=1e-4),
        consume_wh=22011,
    )


@respx.mock
async def test_sign_is_md5_of_message_id_and_timestamp():
    route = respx.post(URL).mock(side_effect=_echo(FIXTURE))
    await _client().read_channels()
    header = json.loads(route.calls[0].request.content)["header"]
    expected = hashlib.md5(f"{header['messageId']}{header['timestamp']}".encode()).hexdigest()
    assert header["sign"] == expected
    assert header["uuid"] == UUID


@respx.mock
async def test_request_always_uses_get_and_electricityx_namespace():
    route = respx.post(URL).mock(side_effect=_echo(FIXTURE))
    await _client().read_channels()
    body = json.loads(route.calls[0].request.content)
    assert body["header"]["method"] == "GET"
    assert body["header"]["namespace"] == "Appliance.Control.ElectricityX"
    assert body["payload"] == {"electricity": {"channel": 65535}}


def test_client_exposes_no_write_method():
    public = [
        name
        for name, _ in inspect.getmembers(RefossClient, inspect.isfunction)
        if not name.startswith("_")
    ]
    assert public == ["read_channels", "read_hourly"]


@respx.mock
async def test_wrong_message_id_in_reply_raises_refoss_error():
    respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "header": {"messageId": "someone-else", "method": "GETACK"},
                "payload": {"electricity": FIXTURE},
            },
        )
    )
    with pytest.raises(RefossError):
        await _client().read_channels()


@respx.mock
async def test_channel_count_other_than_18_raises_refoss_error():
    respx.post(URL).mock(side_effect=_echo(FIXTURE[:17]))
    with pytest.raises(RefossError):
        await _client().read_channels()


@respx.mock
async def test_malformed_channel_raises_refoss_error():
    respx.post(URL).mock(side_effect=_echo([{"channel": 1}] * 18))
    with pytest.raises(RefossError):
        await _client().read_channels()


@respx.mock
async def test_connection_closed_raises_refoss_error():
    respx.post(URL).mock(side_effect=httpx.RemoteProtocolError("closed"))
    with pytest.raises(RefossError):
        await _client().read_channels()


def test_discovery_keeps_only_the_configured_host():
    from adscontrol.refoss.client import uuid_from_reply

    reply = json.dumps({"ip": "192.168.4.254", "uuid": "abc", "channels": []}).encode()
    assert uuid_from_reply(reply, "192.168.4.254", "192.168.4.254") == "abc"
    assert uuid_from_reply(reply, "192.168.4.9", "192.168.4.254") is None
    assert uuid_from_reply(b"not json", "192.168.4.254", "192.168.4.254") is None


NOW = datetime(2026, 11, 5, 5, 26, 46, tzinfo=timezone.utc)


def _hourly_reply(request: httpx.Request) -> httpx.Response:
    header = json.loads(request.content)["header"]
    # Shaped like a captured reply: unordered, stamped at the end of each hour, newest partial.
    data = [
        {
            "timestamp": int(datetime(2026, 11, 5, 4, 59, tzinfo=timezone.utc).timestamp()),
            "value": 339,
        },
        {
            "timestamp": int(datetime(2026, 11, 4, 22, 59, tzinfo=timezone.utc).timestamp()),
            "value": 293,
        },
        {
            "timestamp": int(datetime(2026, 11, 5, 5, 26, 40, tzinfo=timezone.utc).timestamp()),
            "value": 12,
        },
        {
            "timestamp": int(datetime(2026, 11, 5, 1, 59, 1, tzinfo=timezone.utc).timestamp()),
            "value": 164,
        },
    ]
    return httpx.Response(
        200,
        json={
            "header": {"messageId": header["messageId"], "method": "GETACK"},
            "payload": {"consumptionH": [{"channel": 17, "total": 0, "data": data}]},
        },
    )


@respx.mock
async def test_read_hourly_returns_complete_hours_by_timestamp():
    route = respx.post(URL).mock(side_effect=_hourly_reply)
    hours = await _client().read_hourly(17, now=NOW)
    assert hours == [
        (datetime(2026, 11, 4, 22, tzinfo=timezone.utc), 293),
        (datetime(2026, 11, 5, 1, tzinfo=timezone.utc), 164),
        (datetime(2026, 11, 5, 4, tzinfo=timezone.utc), 339),
    ]
    body = json.loads(route.calls[0].request.content)
    assert body["header"]["method"] == "GET"
    assert body["header"]["namespace"] == "Appliance.Control.ConsumptionH"
    # An empty payload makes the device drop the connection; the channel is always named.
    assert body["payload"] == {"consumptionH": [{"channel": 17}]}


def test_only_read_namespaces_can_be_requested():
    assert READ_NAMESPACES == ("Appliance.Control.ElectricityX", "Appliance.Control.ConsumptionH")
    with pytest.raises(ValueError):
        _client()._request("Appliance.Control.Bind", {})
