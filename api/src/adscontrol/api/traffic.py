"""Georgia 511 traffic cameras from the household's own list. The browser loads the pictures.

Live video comes from Georgia DOT's stream servers, which any page may play, but the short-lived
token for it comes from 511GA's own site, which browsers can't call from here; so this asks.
"""

from urllib.parse import urlparse

import httpx
import yaml
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/traffic")
IMAGE_URL = "https://511ga.org/map/Cctv/{view}"  # 511GA refreshes each picture about once a minute
# shortcut: the address 511GA's own camera page uses, not its documented API; may change without notice.
VIDEO_URL = "https://511ga.org/Camera/GetVideoUrl"
STREAM_HOST = ".navigator.dot.ga.gov"


def _cameras(request: Request) -> list[dict]:
    path = request.app.state.settings.traffic_cameras_path
    try:
        entries = yaml.safe_load(path.read_text()) or []
    except FileNotFoundError:
        entries = []
    # a whole number only, so a typo can't point the browser somewhere else
    return [e for e in entries if isinstance(e, dict) and type(e.get("view")) is int]


@router.get("")
async def traffic_cameras(request: Request) -> dict:
    return {
        "cameras": [
            {
                "nickname": str(e.get("nickname") or e.get("name") or e["view"]),
                "name": str(e.get("name") or ""),
                "view": e["view"],
                "image_url": IMAGE_URL.format(view=e["view"]),
                "home": bool(e.get("home")),
            }
            for e in _cameras(request)
        ]
    }


@router.get("/{view}/video")
async def video(view: int, request: Request) -> dict:
    if view not in {e["view"] for e in _cameras(request)}:
        raise HTTPException(status_code=404, detail="not one of our traffic cameras")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(VIDEO_URL, params={"imageId": view})
        response.raise_for_status()
        url = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Georgia 511 isn't answering") from exc
    parts = urlparse(url) if isinstance(url, str) else None
    if not parts or parts.scheme != "https" or not (parts.hostname or "").endswith(STREAM_HOST):
        raise HTTPException(status_code=503, detail="Georgia 511 gave no video for this camera")
    return {"url": url}
