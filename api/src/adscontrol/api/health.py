from datetime import datetime, timezone

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/health")
async def health(request: Request) -> dict:
    now = datetime.now(timezone.utc)
    states = request.app.state.source_states
    database = await request.app.state.db_check()
    sources = {
        name: {
            "last_success": state.last_success,
            "last_error": state.last_error,
            "interval_s": state.interval_s,
            "healthy": state.healthy(now),
        }
        for name, state in states.items()
    }
    ok = database and all(s["healthy"] for s in sources.values())
    return {"status": "ok" if ok else "degraded", "database": database, "sources": sources}


def stopped_since(request: Request, source: str) -> dict | None:
    """A feed that is failing now, past one missed poll, with when it last worked (None: never)."""
    state = request.app.state.source_states.get(source)
    if state is None or state.last_error is None or state.healthy(datetime.now(timezone.utc)):
        return None
    return {"since": state.last_success}
