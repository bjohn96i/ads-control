"""FastAPI application factory: wires the database, jobs and routes."""

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from adscontrol.api import energy, health, live, maintenance
from adscontrol.config import ROOT_DIR, Settings, get_settings
from adscontrol.db.engine import create_engine, make_session_factory
from adscontrol.refoss.recorder import SAMPLE_INTERVAL_S, Recorder
from adscontrol.scheduler import Job, Scheduler, SourceState


def create_app(
    settings: Settings | None = None,
    *,
    db_check: Callable[[], Awaitable[bool]] | None = None,
    jobs: list[Job] | None = None,
    start_jobs: bool = True,
    web_dir: Path = ROOT_DIR / "web" / "dist",
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
    app.state.clock = lambda: datetime.now(timezone.utc)
    app.include_router(health.router)
    app.include_router(live.router)
    app.include_router(energy.router)
    app.include_router(maintenance.router)

    if (web_dir / "index.html").exists():
        if (web_dir / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=web_dir / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def page(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(status_code=404)
            candidate = (web_dir / path).resolve()
            if candidate.is_file() and candidate.is_relative_to(web_dir.resolve()):
                return FileResponse(candidate)
            return FileResponse(web_dir / "index.html")

    return app
