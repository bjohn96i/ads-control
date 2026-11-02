from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from adscontrol.app import create_app
from adscontrol.scheduler import Job, SourceState


async def _db_ok() -> bool:
    return True


async def _noop() -> None:
    return None


def _client(states: dict[str, SourceState], jobs: list[Job]) -> TestClient:
    app = create_app(db_check=_db_ok, jobs=jobs, start_jobs=False)
    app.state.source_states = states
    return TestClient(app)


def test_health_ok_with_no_sources():
    body = _client({}, []).get("/api/health").json()
    assert body["status"] == "ok"
    assert body["sources"] == {}


def test_health_reports_degraded_when_source_overdue():
    job = Job("refoss", 10, _noop)
    overdue = datetime.now(timezone.utc) - timedelta(seconds=31)
    states = {"refoss": SourceState(interval_s=10, last_success=overdue)}
    body = _client(states, [job]).get("/api/health").json()
    assert body["status"] == "degraded"
    assert body["sources"]["refoss"]["interval_s"] == 10


def test_health_degraded_when_database_down():
    async def db_down() -> bool:
        return False

    app = create_app(db_check=db_down, jobs=[], start_jobs=False)
    assert TestClient(app).get("/api/health").json()["status"] == "degraded"


def test_source_that_never_succeeded_is_degraded():
    job = Job("refoss", 10, _noop)
    states = {"refoss": SourceState(interval_s=10, last_error="boom")}
    body = _client(states, [job]).get("/api/health").json()
    assert body["status"] == "degraded"
    assert body["sources"]["refoss"]["last_error"] == "boom"
