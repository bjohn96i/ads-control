"""Camera events and live video. Google's tokens stay here; the browser sees only the answer."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from adscontrol.api.maintenance import require_action
from adscontrol.auth import require_pin
from adscontrol.nest.sdm import NestError

router = APIRouter(prefix="/api/cameras")
guarded = [Depends(require_action), Depends(require_pin)]


class LiveIn(BaseModel):
    offer_sdp: str = Field(min_length=1, max_length=20_000)


async def _device_id(request: Request, camera_id: int) -> str:
    async with request.app.state.sessions() as session:
        device_id = await session.scalar(
            text("SELECT device_id FROM cameras WHERE id = :i"), {"i": camera_id}
        )
    if device_id is None:
        raise HTTPException(status_code=404, detail="no such camera")
    return device_id


def _sdm(request: Request):
    if request.app.state.sdm is None:
        raise HTTPException(status_code=503, detail="Google is not set up")
    return request.app.state.sdm


@router.get("")
async def list_cameras(request: Request) -> dict:
    async with request.app.state.sessions() as session:
        rows = await session.execute(
            text(
                """
                SELECT c.id, c.name, c.kind, e.type AS last_event, e.occurred_at AS last_event_at
                FROM cameras c LEFT JOIN LATERAL (
                    SELECT type, occurred_at FROM camera_events
                    WHERE camera_id = c.id ORDER BY occurred_at DESC LIMIT 1
                ) e ON true
                ORDER BY c.id
                """
            )
        )
        cameras = rows.all()
    return {
        "cameras": [
            {
                "id": c.id,
                "name": c.name,
                "kind": c.kind,
                "last_event": c.last_event,
                "last_event_at": c.last_event_at,
            }
            for c in cameras
        ]
    }


@router.get("/events")
async def recent_events(request: Request, limit: int = Query(25, ge=1, le=100)) -> dict:
    async with request.app.state.sessions() as session:
        rows = await session.execute(
            text(
                """
                SELECT e.camera_id, c.name AS camera, e.type, e.occurred_at
                FROM camera_events e JOIN cameras c ON c.id = e.camera_id
                ORDER BY e.occurred_at DESC LIMIT :n
                """
            ),
            {"n": limit},
        )
        return {"events": [dict(r._mapping) for r in rows]}


@router.post("/{camera_id}/live", dependencies=guarded)
async def start_live(camera_id: int, body: LiveIn, request: Request) -> dict:
    device_id = await _device_id(request, camera_id)
    try:
        return await _sdm(request).generate_stream(device_id, body.offer_sdp)
    except NestError as exc:
        raise HTTPException(
            status_code=409, detail="This camera isn't available for live video right now."
        ) from exc


@router.delete("/{camera_id}/live/{session_id}", status_code=204, dependencies=guarded)
async def stop_live(camera_id: int, session_id: str, request: Request) -> None:
    device_id = await _device_id(request, camera_id)
    try:
        await _sdm(request).stop_stream(device_id, session_id)
    except NestError:
        pass  # it ends by itself within five minutes anyway
