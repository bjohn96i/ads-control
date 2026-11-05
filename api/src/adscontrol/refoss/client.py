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
from datetime import datetime, timedelta, timezone

import httpx

CHANNEL_COUNT = 18
DISCOVERY_MESSAGE = json.dumps({"id": "48cbd88f969eb3c486085cfe7b5eb1e4", "devName": "*"}).encode()
HISTORY_WINDOW = timedelta(hours=49)  # the monitor keeps 48 hourly slots, plus the current one
READ_NAMESPACES = ("Appliance.Control.ElectricityX", "Appliance.Control.ConsumptionH")
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

    def _request(self, namespace: str, payload: dict) -> tuple[dict, str]:
        # Only reads: the same protocol can switch relays and change settings.
        if namespace not in READ_NAMESPACES:
            raise ValueError(f"{namespace} is not a read namespace")
        tag = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(16))
        message_id = hashlib.md5(tag.encode()).hexdigest()
        timestamp = int(time.time())
        return (
            {
                "header": {
                    "from": f"/app/{tag}/subscribe",
                    "messageId": message_id,
                    "method": "GET",
                    "namespace": namespace,
                    "payloadVersion": 1,
                    "sign": hashlib.md5(f"{message_id}{timestamp}".encode()).hexdigest(),
                    "timestamp": timestamp,
                    "triggerSrc": "ADSControl",
                    "uuid": self._uuid,
                },
                "payload": payload,
            },
            message_id,
        )

    async def _get(self, namespace: str, payload: dict) -> dict:
        body, message_id = self._request(namespace, payload)
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.post(self._url, json=body)
        data = response.json()
        header = data["header"]
        if header["messageId"] != message_id or header["method"] != "GETACK":
            raise RefossError("reply does not match the request")
        return data["payload"]

    async def read_channels(self) -> list[ChannelReading]:
        try:
            payload = await self._get(
                "Appliance.Control.ElectricityX", {"electricity": {"channel": 65535}}
            )
            readings = [
                ChannelReading(
                    channel=c["channel"],
                    power_w=c["power"] / 1000,
                    voltage_v=c["voltage"] / 1000,
                    current_a=c["current"] / 1000,
                    power_factor=c["factor"],
                    consume_wh=c["mConsume"],
                )
                for c in payload["electricity"]
            ]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise RefossError(f"bad reply: {type(exc).__name__}: {exc}") from exc
        if len(readings) != CHANNEL_COUNT:
            raise RefossError(f"expected {CHANNEL_COUNT} channels, got {len(readings)}")
        return readings

    async def read_hourly(
        self, channel: int, now: datetime | None = None
    ) -> list[tuple[datetime, int]]:
        """Complete hours of the monitor's own hourly history for one channel, oldest first.

        Each entry is stamped (UTC epoch) at the end of its hour and holds raw Wh; the list is
        unordered and not always contiguous, and the current hour's entry is partial, so it's left
        out. The channel is always named: the device drops the connection on an empty payload.
        """
        current = (now or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)
        try:
            payload = await self._get(
                "Appliance.Control.ConsumptionH", {"consumptionH": [{"channel": channel}]}
            )
            entry = payload["consumptionH"][0]
            if entry["channel"] != channel:
                raise RefossError(f"asked for channel {channel}, got {entry['channel']}")
            entries = entry["data"]
            hours = {
                datetime.fromtimestamp(e["timestamp"], timezone.utc).replace(
                    minute=0, second=0, microsecond=0
                ): int(e["value"])
                for e in entries
            }
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
            raise RefossError(f"bad reply: {type(exc).__name__}: {exc}") from exc
        # Empty slots (timestamp 0) and anything older than the monitor's 48 hours are leftovers.
        oldest = current - HISTORY_WINDOW
        return sorted((h, wh) for h, wh in hours.items() if oldest <= h < current)
