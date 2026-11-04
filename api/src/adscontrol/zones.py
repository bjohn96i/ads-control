"""Zones: named groups of monitor channels."""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class Zone:
    id: int
    name: str
    channels: list[int]
    multiplier: float
    kind: str
    pin_x: float
    pin_y: float
    seasonal: bool
    room: str | None = None
    floor: str | None = None


async def list_zones(session: AsyncSession) -> list[Zone]:
    rows = await session.execute(
        text(
            "SELECT id, name, channels, multiplier, kind, pin_x, pin_y, seasonal, room, floor FROM zones ORDER BY id"
        )
    )
    return [Zone(**row._mapping) for row in rows]


def zone_power(zone: Zone, by_channel: dict[int, float]) -> float | None:
    if any(c not in by_channel for c in zone.channels):
        return None
    return sum(by_channel[c] for c in zone.channels) * zone.multiplier
