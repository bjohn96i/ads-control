"""Camera events from Google's feed, and the doorbell's latest picture from its preview clips.

Nothing here opens a video stream: that only happens when a person presses Watch live, so a
battery camera is never woken just to refresh the page.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from adscontrol.cameras.frame import still_frame
from adscontrol.nest.sdm import NestError

log = logging.getLogger(__name__)

EVENT_POLL_S = 5
CAMERA_SYNC_S = 3600
_EVENT_TYPES = {
    "sdm.devices.events.CameraMotion.Motion": "motion",
    "sdm.devices.events.CameraPerson.Person": "person",
    "sdm.devices.events.CameraSound.Sound": "sound",
    "sdm.devices.events.DoorbellChime.Chime": "chime",
}
_CLIP = "sdm.devices.events.CameraClipPreview.ClipPreview"


@dataclass(frozen=True)
class CameraEvent:
    device_id: str
    type: str
    event_id: str
    occurred_at: datetime


@dataclass(frozen=True)
class ClipPreview:
    device_id: str
    url: str
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


def parse_clip(payload: dict) -> ClipPreview | None:
    """The doorbell's preview clip, sent alongside its events or in a message of its own."""
    read = _read(payload)
    if read is None:
        return None
    device_id, occurred, events = read
    url = (events.get(_CLIP) or {}).get("previewUrl")
    return ClipPreview(device_id, url, occurred) if isinstance(url, str) else None


class CameraService:
    def __init__(
        self,
        sdm,
        subscription: str,
        sessions: async_sessionmaker[AsyncSession],
        image_dir: Path,
    ) -> None:
        self._sdm = sdm
        self._subscription = subscription
        self._sessions = sessions
        self._image_dir = image_dir

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

    async def _store_clip_frame(self, session, clip: ClipPreview) -> None:
        camera_id = await self._camera_id(session, clip.device_id)
        if camera_id is None:
            return
        image_at = await session.scalar(
            text("SELECT image_at FROM cameras WHERE id = :i"), {"i": camera_id}
        )
        if image_at is not None and image_at >= clip.occurred_at:
            return  # the feed is not ordered; a late older clip must not replace a newer picture
        try:
            image = await asyncio.to_thread(still_frame, await self._sdm.fetch_clip(clip.url))
        except (NestError, ValueError) as exc:
            log.warning("no image from a preview clip: %s", exc)
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
            {"t": clip.occurred_at, "i": camera_id},
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
                clip = parse_clip(payload or {})
                if clip is not None:
                    await self._store_clip_frame(session, clip)
            await session.commit()
        # Only after the commit: a crash before this means Google sends them again, safely.
        await self._sdm.ack_events(self._subscription, [ack_id for ack_id, _ in messages])
