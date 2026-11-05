"""Polls the monitor and stores one row per channel. A failed poll stores nothing."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from adscontrol.refoss.client import RefossClient, RefossError, discover_uuid

SAMPLE_INTERVAL_S = 10

_INSERT = text(
    """
    INSERT INTO channel_readings (time, channel, power_w, voltage_v, current_a, power_factor, consume_wh)
    VALUES (:time, :channel, :power_w, :voltage_v, :current_a, :power_factor, :consume_wh)
    """
)

log = logging.getLogger(__name__)


async def known_uuid(
    host: str, uuid_path: Path | None, discover: Callable[[str], Awaitable[str]]
) -> str:
    """The monitor's id, discovered once and remembered (delete the file if it's ever replaced).

    Discovery is a UDP broadcast that now and then goes unanswered; reads are unicast and steady.
    """
    remembered = ""
    if uuid_path is not None and uuid_path.exists():
        remembered = uuid_path.read_text().strip()
    if remembered:
        return remembered
    uuid = await discover(host)
    if uuid_path is not None:
        try:
            uuid_path.write_text(uuid + "\n")
        except OSError as exc:  # remembering is a convenience; a gap in the recording is not
            log.warning("could not remember the monitor id in %s: %s", uuid_path, exc)
    return uuid


class Recorder:
    def __init__(
        self,
        host: str,
        sessions: async_sessionmaker[AsyncSession],
        *,
        discover: Callable[[str], Awaitable[str]] = discover_uuid,
        make_client: Callable[[str, str], RefossClient] = RefossClient,
        uuid_path: Path | None = None,
    ) -> None:
        self._host = host
        self._sessions = sessions
        self._discover = discover
        self._make_client = make_client
        self._uuid_path = uuid_path
        self._client = None

    async def _uuid(self) -> str:
        return await known_uuid(self._host, self._uuid_path, self._discover)

    async def poll(self) -> None:
        if self._client is None:
            self._client = self._make_client(self._host, await self._uuid())
        try:
            readings = await self._client.read_channels()
        except RefossError:
            self._client = None  # reconnect next time, with the remembered uuid
            raise
        now = datetime.now(timezone.utc)
        async with self._sessions() as session:
            await session.execute(_INSERT, [{"time": now, **asdict(r)} for r in readings])
            await session.commit()
