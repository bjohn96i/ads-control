"""Outdoor temperature and conditions from Open-Meteo. Only a city-level location (one decimal, ~11 km) ever leaves the house."""

from collections.abc import Callable
from datetime import datetime, timezone

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

WEATHER_INTERVAL_S = 900
_URL = "https://api.open-meteo.com/v1/forecast"


class WeatherRecorder:
    def __init__(
        self,
        lat: float,
        lon: float,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._params = {
            "latitude": round(lat, 1),
            "longitude": round(lon, 1),
            "current": "temperature_2m,weather_code,is_day",
        }
        self._sessions = sessions
        self._clock = clock

    async def poll(self) -> None:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(_URL, params=self._params)
        response.raise_for_status()
        current = response.json()["current"]
        async with self._sessions() as session:
            await session.execute(
                text(
                    "INSERT INTO outdoor_readings VALUES (:t, :c, :w, :d) ON CONFLICT (time) DO NOTHING"
                ),
                {
                    "t": self._clock(),
                    "c": current["temperature_2m"],
                    "w": current.get("weather_code"),
                    "d": None if current.get("is_day") is None else bool(current["is_day"]),
                },
            )
            await session.commit()
