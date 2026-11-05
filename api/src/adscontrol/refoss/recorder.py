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
        # Discovery is a broadcast the monitor's Wi-Fi often misses while idle; reads are unicast.
        # The uuid never changes, so it is found once and remembered (delete the file if the
        # monitor is ever replaced).
        remembered = ""
        if self._uuid_path is not None and self._uuid_path.exists():
            remembered = self._uuid_path.read_text().strip()
        if remembered:
            return remembered
        uuid = await self._discover(self._host)
        if self._uuid_path is not None:
            try:
                self._uuid_path.write_text(uuid + "\n")
            except OSError as exc:  # remembering is a convenience; a gap in the recording is not
                log.warning("could not remember the monitor id in %s: %s", self._uuid_path, exc)
        return uuid

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
