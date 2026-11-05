"""FastAPI application factory: wires the database, jobs and routes."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.trustedhost import TrustedHostMiddleware

from adscontrol.api import (
    auth,
    bills,
    cameras,
    climate,
    energy,
    health,
    live,
    maintenance,
    network,
    traffic,
)
from adscontrol.cameras.service import CAMERA_SYNC_S, EVENT_POLL_S, CameraService
from adscontrol.config import ROOT_DIR, Settings, get_settings
from adscontrol.counters import COUNTER_ENERGY_INTERVAL_S, CounterEnergy
from adscontrol.db.engine import create_engine, make_session_factory
from adscontrol.detect.store import run_detection
from adscontrol.nest.sdm import SdmClient
from adscontrol.nest.thermostat import NEST_INTERVAL_S, ThermostatRecorder
from adscontrol.refoss.recorder import SAMPLE_INTERVAL_S, Recorder
from adscontrol.scheduler import Job, Scheduler, SourceState
from adscontrol.weather import WEATHER_INTERVAL_S, WeatherRecorder

DETECT_INTERVAL_S = 900


def jobs_allowed(settings: Settings) -> bool:
    return not settings.hold_path.exists()


def create_app(
    settings: Settings | None = None,
    *,
    db_check: Callable[[], Awaitable[bool]] | None = None,
    jobs: list[Job] | None = None,
    start_jobs: bool | None = None,
    web_dir: Path = ROOT_DIR / "web" / "dist",
) -> FastAPI:
    settings = settings or get_settings()
    if start_jobs is None:
        start_jobs = jobs_allowed(settings)
        if not start_jobs:
            logging.getLogger(__name__).warning("recorder held: %s exists", settings.hold_path)
    engine = create_engine(settings.database_url)
    sessions = make_session_factory(engine)
    sdm = None
    if settings.google_client_id and settings.sdm_project_id:
        sdm = SdmClient(
            settings.google_client_id,
            settings.google_client_secret.get_secret_value(),
            settings.sdm_project_id,
            settings.nest_token_path,
        )
    if jobs is None:
        recorder = Recorder(settings.refoss_host, sessions, uuid_path=settings.refoss_uuid_path)

        async def detect() -> None:
            async with sessions() as session:
                await run_detection(session, datetime.now(timezone.utc))

        jobs = [
            Job("refoss", SAMPLE_INTERVAL_S, recorder.poll),
            Job("counter_energy", COUNTER_ENERGY_INTERVAL_S, CounterEnergy(sessions).run),
            Job("detect", DETECT_INTERVAL_S, detect),
        ]
        if sdm is not None:
            jobs.append(Job("nest", NEST_INTERVAL_S, ThermostatRecorder(sdm, sessions).poll))
            service = CameraService(sdm, settings.google_pubsub_subscription, sessions)
            jobs.append(Job("cameras", CAMERA_SYNC_S, service.sync))
            if settings.google_pubsub_subscription:
                jobs.append(Job("camera_events", EVENT_POLL_S, service.poll))
        if settings.weather_lat is not None and settings.weather_lon is not None:
            weather = WeatherRecorder(settings.weather_lat, settings.weather_lon, sessions)
            jobs.append(Job("weather", WEATHER_INTERVAL_S, weather.poll))
    states = {j.name: SourceState(j.interval_s) for j in jobs}

    async def _db_check() -> bool:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:  # noqa: BLE001 - health reports it; it must not raise
            return False

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        scheduler = Scheduler(jobs, app.state.source_states)
        if start_jobs:
            await scheduler.start()
        yield
        await scheduler.stop()
        await engine.dispose()

    app = FastAPI(title="ADS-Control", lifespan=lifespan)

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.state.settings = settings
    app.state.sdm = sdm
    app.state.sessions = sessions
    app.state.source_states = states
    app.state.db_check = db_check or _db_check
    app.state.clock = lambda: datetime.now(timezone.utc)
    # One PIN check at a time, so simultaneous wrong guesses each count towards the lockout.
    app.state.pin_lock = asyncio.Lock()
    app.include_router(health.router)
    app.include_router(live.router)
    app.include_router(auth.router)
    app.include_router(energy.router)
    app.include_router(climate.router)
    app.include_router(cameras.router)
    app.include_router(bills.router)
    app.include_router(maintenance.router)
    app.include_router(network.router)
    app.include_router(traffic.router)

    if (web_dir / "index.html").exists():
        if (web_dir / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=web_dir / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def page(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(status_code=404)
            candidate = (web_dir / path).resolve()
            # These keep their names across builds, so the browser must check for a new one.
            fresh = {"Cache-Control": "no-cache"}
            if candidate.is_file() and candidate.is_relative_to(web_dir.resolve()):
                return FileResponse(candidate, headers=fresh)
            return FileResponse(web_dir / "index.html", headers=fresh)

    return app
