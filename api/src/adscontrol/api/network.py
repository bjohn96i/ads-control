"""Lanthorn's noisiest devices and globe, borrowed for the home page. Lanthorn owns the data."""

import httpx
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/network")
TOP_DEVICES = 5


@router.get("")
async def network(request: Request) -> dict:
    url = f"{request.app.state.settings.lanthorn_url}/api/overview"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, params={"range": "24h"})
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Lanthorn isn't reachable") from exc
    return {
        "top_devices": (body.get("top_devices") or [])[:TOP_DEVICES],
        "arcs": body.get("arcs") or [],
        "home": body.get("home"),
    }
