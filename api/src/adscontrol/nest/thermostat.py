"""Records what the thermostats report, once a minute. It never changes anything."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NEST_INTERVAL_S = 60


class ThermostatRecorder:
    def __init__(
        self,
        client,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._client = client
        self._sessions = sessions
        self._clock = clock

    async def poll(self) -> None:
        devices = await self._client.list_thermostats()
        now = self._clock()
        async with self._sessions() as session:
            for t in devices:
                thermostat_id = await session.scalar(
                    text(
                        """
                        INSERT INTO thermostats (device_id, name) VALUES (:d, :n)
                        ON CONFLICT (device_id) DO UPDATE SET name = :n RETURNING id
                        """
                    ),
                    {"d": t.device_id, "n": t.name},
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO thermostat_readings VALUES
                        (:time, :id, :ambient, :humidity, :heat, :cool, :mode, :hvac, :eco, :online)
                        """
                    ),
                    {
                        "time": now,
                        "id": thermostat_id,
                        "ambient": t.ambient_c,
                        "humidity": t.humidity,
                        "heat": t.heat_c,
                        "cool": t.cool_c,
                        "mode": t.mode,
                        "hvac": t.hvac_status,
                        "eco": t.eco,
                        "online": t.online,
                    },
                )
            await session.commit()


@dataclass(frozen=True)
class Paired:
    id: int
    device_id: str
    name: str
    zone_id: int | None
    zone_name: str | None


async def list_paired(session: AsyncSession) -> list[Paired]:
    rows = await session.execute(
        text(
            """
            SELECT t.id, t.device_id, t.name, t.zone_id, z.name AS zone_name
            FROM thermostats t LEFT JOIN zones z ON z.id = t.zone_id ORDER BY t.id
            """
        )
    )
    return [Paired(**row._mapping) for row in rows]


async def pair_thermostat(session: AsyncSession, thermostat: str, zone: str) -> None:
    zone_id = await session.scalar(text("SELECT id FROM zones WHERE name = :n"), {"n": zone})
    if zone_id is None:
        raise ValueError(f"no zone named {zone!r}")
    result = await session.execute(
        text("UPDATE thermostats SET zone_id = :z WHERE name = :n"),
        {"z": zone_id, "n": thermostat},
    )
    if result.rowcount == 0:
        raise ValueError(f"no thermostat named {thermostat!r}")
