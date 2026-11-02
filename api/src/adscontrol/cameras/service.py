"""Camera events from Google's feed, and the latest event image for each camera.

Nothing here opens a video stream: that only happens when a person presses Watch live, so a
battery camera is never woken just to refresh the page.
"""

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from adscontrol.nest.sdm import NestError

log = logging.getLogger(__name__)

EVENT_POLL_S = 5
CAMERA_SYNC_S = 3600
IMAGE_VALID_FOR = timedelta(seconds=30)  # Google's limit on downloading an event image
_EVENT_TYPES = {
    "sdm.devices.events.CameraMotion.Motion": "motion",
    "sdm.devices.events.CameraPerson.Person": "person",
    "sdm.devices.events.CameraSound.Sound": "sound",
    "sdm.devices.events.DoorbellChime.Chime": "chime",
}


@dataclass(frozen=True)
class CameraEvent:
    device_id: str
    type: str
    event_id: str
    occurred_at: datetime


def parse_events(payload: dict) -> list[CameraEvent]:
    """One message can carry several events; thermostat updates carry none."""
    update = payload.get("resourceUpdate") or {}
    try:
        occurred = datetime.fromisoformat(payload.get("timestamp", "").replace("Z", "+00:00"))
        device_id = update["name"].rsplit("/", 1)[-1]
    except (ValueError, KeyError, AttributeError):
        return []
    events = update.get("events") or {}
    ignored = sorted(set(events) - set(_EVENT_TYPES))
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
        image_dir: Path,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._sdm = sdm
        self._subscription = subscription
        self._sessions = sessions
        self._image_dir = image_dir
        self._clock = clock

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

    async def _store_image(self, session, camera_id: int, event: CameraEvent) -> None:
        if self._clock() - event.occurred_at > IMAGE_VALID_FOR:
            return
        image_at = await session.scalar(
            text("SELECT image_at FROM cameras WHERE id = :i"), {"i": camera_id}
        )
        if image_at is not None and image_at >= event.occurred_at:
            return  # the feed is not ordered; a late older event must not replace a newer picture
        try:
            image = await self._sdm.fetch_event_image(event.device_id, event.event_id)
        except NestError as exc:
            log.warning("no image for a %s event: %s", event.type, exc)
            return
        self._image_dir.mkdir(parents=True, exist_ok=True)
        target = self._image_dir / f"{camera_id}.jpg"
        temporary = target.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(image)
        temporary.replace(target)
        await session.execute(
            text("UPDATE cameras SET image_at = :t WHERE id = :i"),
            {"t": event.occurred_at, "i": camera_id},
        )

    async def _record(self, session, event: CameraEvent) -> None:
        camera_id = await self._camera_id(session, event.device_id)
        if camera_id is None:
            await self.sync()
            camera_id = await self._camera_id(session, event.device_id)
        if camera_id is None:
            return
        inserted = await session.scalar(
            text(
                """
                INSERT INTO camera_events (camera_id, type, occurred_at, event_id)
                VALUES (:c, :t, :o, :e) ON CONFLICT (event_id) DO NOTHING RETURNING id
                """
            ),
            {"c": camera_id, "t": event.type, "o": event.occurred_at, "e": event.event_id},
        )
        if inserted is not None:
            await self._store_image(session, camera_id, event)

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
