"""FastAPI application factory: wires the database, jobs and routes."""

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from adscontrol.api import health
from adscontrol.config import Settings, get_settings
from adscontrol.db.engine import create_engine, make_session_factory
from adscontrol.refoss.recorder import SAMPLE_INTERVAL_S, Recorder
from adscontrol.scheduler import Job, Scheduler, SourceState


def create_app(
    settings: Settings | None = None,
    *,
    db_check: Callable[[], Awaitable[bool]] | None = None,
    jobs: list[Job] | None = None,
    start_jobs: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    engine = create_engine(settings.database_url)
    sessions = make_session_factory(engine)
    if jobs is None:
        recorder = Recorder(settings.refoss_host, sessions)
        jobs = [Job("refoss", SAMPLE_INTERVAL_S, recorder.poll)]
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
    app.state.settings = settings
    app.state.sessions = sessions
    app.state.source_states = states
    app.state.db_check = db_check or _db_check
    app.include_router(health.router)
    return app
