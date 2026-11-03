"""Camera events from Google's feed. Google gives no event pictures for these WebRTC cameras.

Nothing here opens a video stream: that only happens when a person presses Watch live, so a
battery camera is never woken just to refresh the page.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = logging.getLogger(__name__)

EVENT_POLL_S = 5
CAMERA_SYNC_S = 3600
_EVENT_TYPES = {
    "sdm.devices.events.CameraMotion.Motion": "motion",
    "sdm.devices.events.CameraPerson.Person": "person",
    "sdm.devices.events.CameraSound.Sound": "sound",
    "sdm.devices.events.DoorbellChime.Chime": "chime",
}
# The doorbell also sends preview clips; they are not used.
_CLIP = "sdm.devices.events.CameraClipPreview.ClipPreview"


@dataclass(frozen=True)
class CameraEvent:
    device_id: str
    type: str
    event_id: str
    occurred_at: datetime


def _read(payload: dict) -> tuple[str, datetime, dict] | None:
    update = payload.get("resourceUpdate") or {}
    try:
        occurred = datetime.fromisoformat(payload.get("timestamp", "").replace("Z", "+00:00"))
        device_id = update["name"].rsplit("/", 1)[-1]
    except (ValueError, KeyError, AttributeError):
        return None
    return device_id, occurred, update.get("events") or {}


def parse_events(payload: dict) -> list[CameraEvent]:
    """One message can carry several events; thermostat updates carry none."""
    read = _read(payload)
    if read is None:
        return []
    device_id, occurred, events = read
    ignored = sorted(set(events) - set(_EVENT_TYPES) - {_CLIP})
    if ignored:
        log.warning("ignored camera event types: %s", ignored)
    return [
        CameraEvent(device_id, _EVENT_TYPES[name], body["eventId"], occurred)
        for name, body in events.items()
        if name in _EVENT_TYPES and "eventId" in body
    ]


class CameraService:
    def __init__(
        self,
        sdm,
        subscription: str,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._sdm = sdm
        self._subscription = subscription
        self._sessions = sessions

    async def sync(self) -> None:
        cameras = await self._sdm.list_cameras()
        async with self._sessions() as session:
            for camera in cameras:
                await session.execute(
                    text(
                        """
                        INSERT INTO cameras (device_id, name, kind) VALUES (:d, :n, :k)
                        ON CONFLICT (device_id) DO UPDATE SET name = :n, kind = :k
                        """
                    ),
                    {"d": camera.device_id, "n": camera.name, "k": camera.kind},
                )
            await session.commit()

    async def _camera_id(self, session: AsyncSession, device_id: str) -> int | None:
        return await session.scalar(
            text("SELECT id FROM cameras WHERE device_id = :d"), {"d": device_id}
        )

    async def _record(self, session, event: CameraEvent) -> None:
        camera_id = await self._camera_id(session, event.device_id)
        if camera_id is None:
            await self.sync()
            camera_id = await self._camera_id(session, event.device_id)
        if camera_id is None:
            return
        await session.execute(
            text(
                """
                INSERT INTO camera_events (camera_id, type, occurred_at, event_id)
                VALUES (:c, :t, :o, :e) ON CONFLICT (event_id) DO NOTHING
                """
            ),
            {"c": camera_id, "t": event.type, "o": event.occurred_at, "e": event.event_id},
        )

    async def poll(self) -> None:
        messages = await self._sdm.pull_events(self._subscription)
        if not messages:
            return
        async with self._sessions() as session:
            for _, payload in messages:
                for event in parse_events(payload or {}):
                    await self._record(session, event)
            await session.commit()
        # Only after the commit: a crash before this means Google sends them again, safely.
        await self._sdm.ack_events(self._subscription, [ack_id for ack_id, _ in messages])
