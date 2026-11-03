"""Georgia 511 traffic cameras from the household's own list. The browser loads the pictures."""

import yaml
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/traffic")
IMAGE_URL = "https://511ga.org/map/Cctv/{view}"  # 511GA refreshes each picture about once a minute


@router.get("")
async def traffic_cameras(request: Request) -> dict:
    path = request.app.state.settings.traffic_cameras_path
    try:
        entries = yaml.safe_load(path.read_text()) or []
    except FileNotFoundError:
        entries = []
    return {
        "cameras": [
            {
                "nickname": str(e.get("nickname") or e.get("name") or e["view"]),
                "name": str(e.get("name") or ""),
                "image_url": IMAGE_URL.format(view=e["view"]),
                "home": bool(e.get("home")),
            }
            for e in entries
            # a whole number only, so a typo can't point the browser somewhere else
            if isinstance(e, dict) and type(e.get("view")) is int
        ]
    }
