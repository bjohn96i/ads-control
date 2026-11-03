import httpx
import respx
from fastapi.testclient import TestClient

from adscontrol.app import create_app
from adscontrol.config import Settings

LANTHORN = "http://lanthorn.test:8000"
OVERVIEW = {
    "kpis": {"open_alerts": 2},
    "top_devices": [
        {
            "id": f"d{i}",
            "name": f"Device {i}",
            "device_type": "iot",
            "queries": 100 - i,
            "blocked": i,
        }
        for i in range(8)
    ],
    "arcs": [
        {
            "lat": 37.8,
            "lon": -97.8,
            "country_code": "US",
            "country": "United States",
            "queries": 900,
            "blocked": 4,
            "state": "normal",
        },
    ],
    "home": {"lat": 33.75, "lon": -84.39},
    "sources": {},
    "recent_alerts": [{"title": "secret detail"}],
}


async def _db_ok() -> bool:
    return True


def _client() -> TestClient:
    app = create_app(Settings(lanthorn_url=LANTHORN), db_check=_db_ok, jobs=[], start_jobs=False)
    return TestClient(app)


@respx.mock
def test_network_passes_on_top_five_devices_arcs_and_home():
    route = respx.get(f"{LANTHORN}/api/overview").mock(
        return_value=httpx.Response(200, json=OVERVIEW)
    )
    body = _client().get("/api/network").json()
    assert route.calls[0].request.url.params["range"] == "24h"
    assert [d["name"] for d in body["top_devices"]] == [f"Device {i}" for i in range(5)]
    assert body["arcs"] == OVERVIEW["arcs"]
    assert body["home"] == {"lat": 33.75, "lon": -84.39}
    # only what the panel draws; Lanthorn's alerts stay in Lanthorn
    assert set(body) == {"top_devices", "arcs", "home"}


@respx.mock
def test_lanthorn_down_is_a_503_that_says_so():
    respx.get(f"{LANTHORN}/api/overview").mock(side_effect=httpx.ConnectError("refused"))
    r = _client().get("/api/network")
    assert r.status_code == 503
    assert "Lanthorn" in r.json()["detail"]


@respx.mock
def test_lanthorn_error_is_a_503():
    respx.get(f"{LANTHORN}/api/overview").mock(return_value=httpx.Response(500))
    assert _client().get("/api/network").status_code == 503
