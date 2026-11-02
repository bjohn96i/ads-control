"""Camera tiles and live video. Google's tokens stay here; the browser sees only the answer."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
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
    now = request.app.state.clock()
    async with request.app.state.sessions() as session:
        rows = await session.execute(
            text(
                """
                SELECT c.id, c.name, c.kind, c.image_at, e.type AS last_event, e.occurred_at AS last_event_at
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
                "has_image": c.image_at is not None,
                "image_age_s": (now - c.image_at).total_seconds() if c.image_at else None,
            }
            for c in cameras
        ]
    }


@router.get("/{camera_id}/image", dependencies=[Depends(require_pin)])
async def image(camera_id: int, request: Request) -> FileResponse:
    path = request.app.state.settings.camera_image_dir / f"{camera_id}.jpg"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="no image yet")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


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
