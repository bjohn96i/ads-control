"""Read-only client for the Refoss EM16 on the LAN.

Protocol from the refoss_ha library. This module only ever sends method GET: the same protocol
can switch relays (togglex), so no method or namespace parameter exists to be misused.
"""

import asyncio
import hashlib
import json
import secrets
import socket
import string
import time
from dataclasses import dataclass

import httpx

CHANNEL_COUNT = 18
DISCOVERY_MESSAGE = json.dumps({"id": "48cbd88f969eb3c486085cfe7b5eb1e4", "devName": "*"}).encode()
DISCOVERY_SEND_PORT = 9988
DISCOVERY_LISTEN_PORT = 9989


class RefossError(Exception):
    """The monitor could not be reached, or answered with something unusable."""


@dataclass(frozen=True)
class ChannelReading:
    channel: int
    power_w: float
    voltage_v: float
    current_a: float
    power_factor: float
    consume_wh: int


def uuid_from_reply(data: bytes, source_ip: str, host: str) -> str | None:
    if source_ip != host:
        return None
    try:
        return json.loads(data).get("uuid")
    except (ValueError, AttributeError):
        return None


async def discover_uuid(host: str, timeout: float = 5.0) -> str:
    """Ask the LAN who is there. The device answers a broadcast, not a unicast."""
    loop = asyncio.get_running_loop()
    found: asyncio.Future[str] = loop.create_future()

    class _Protocol(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
            uuid = uuid_from_reply(data, addr[0], host)
            if uuid and not found.done():
                found.set_result(uuid)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", DISCOVERY_LISTEN_PORT))
    except OSError as exc:
        sock.close()
        raise RefossError(f"cannot listen on port {DISCOVERY_LISTEN_PORT}: {exc}") from exc
    transport, _ = await loop.create_datagram_endpoint(_Protocol, sock=sock)
    try:
        transport.sendto(DISCOVERY_MESSAGE, ("255.255.255.255", DISCOVERY_SEND_PORT))
        return await asyncio.wait_for(found, timeout)
    except (TimeoutError, OSError) as exc:
        raise RefossError(f"no discovery reply from {host}") from exc
    finally:
        transport.close()


class RefossClient:
    def __init__(self, host: str, uuid: str) -> None:
        self._url = f"http://{host}/public"
        self._uuid = uuid

    def _request(self) -> tuple[dict, str]:
        tag = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(16))
        message_id = hashlib.md5(tag.encode()).hexdigest()
        timestamp = int(time.time())
        return (
            {
                "header": {
                    "from": f"/app/{tag}/subscribe",
                    "messageId": message_id,
                    "method": "GET",
                    "namespace": "Appliance.Control.ElectricityX",
                    "payloadVersion": 1,
                    "sign": hashlib.md5(f"{message_id}{timestamp}".encode()).hexdigest(),
                    "timestamp": timestamp,
                    "triggerSrc": "ADSControl",
                    "uuid": self._uuid,
                },
                "payload": {"electricity": {"channel": 65535}},
            },
            message_id,
        )

    async def read_channels(self) -> list[ChannelReading]:
        body, message_id = self._request()
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.post(self._url, json=body)
            data = response.json()
            header = data["header"]
            if header["messageId"] != message_id or header["method"] != "GETACK":
                raise RefossError("reply does not match the request")
            readings = [
                ChannelReading(
                    channel=c["channel"],
                    power_w=c["power"] / 1000,
                    voltage_v=c["voltage"] / 1000,
                    current_a=c["current"] / 1000,
                    power_factor=c["factor"],
                    consume_wh=c["mConsume"],
                )
                for c in data["payload"]["electricity"]
            ]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise RefossError(f"bad reply: {type(exc).__name__}: {exc}") from exc
        if len(readings) != CHANNEL_COUNT:
            raise RefossError(f"expected {CHANNEL_COUNT} channels, got {len(readings)}")
        return readings
