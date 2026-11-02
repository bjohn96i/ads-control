"""Polls the monitor and stores one row per channel. A failed poll stores nothing."""

from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import datetime, timezone

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


class Recorder:
    def __init__(
        self,
        host: str,
        sessions: async_sessionmaker[AsyncSession],
        *,
        discover: Callable[[str], Awaitable[str]] = discover_uuid,
        make_client: Callable[[str, str], RefossClient] = RefossClient,
    ) -> None:
        self._host = host
        self._sessions = sessions
        self._discover = discover
        self._make_client = make_client
        self._client = None

    async def poll(self) -> None:
        if self._client is None:
            self._client = self._make_client(self._host, await self._discover(self._host))
        try:
            readings = await self._client.read_channels()
        except RefossError:
            self._client = None  # the device may have rebooted or been replaced; ask again
            raise
        now = datetime.now(timezone.utc)
        async with self._sessions() as session:
            await session.execute(_INSERT, [{"time": now, **asdict(r)} for r in readings])
            await session.commit()
