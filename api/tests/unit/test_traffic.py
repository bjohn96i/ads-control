import httpx
import respx
from fastapi.testclient import TestClient

from adscontrol.app import create_app
from adscontrol.config import Settings


async def _db_ok() -> bool:
    return True


def _client(tmp_path, text: str | None) -> TestClient:
    path = tmp_path / "traffic_cameras.yaml"
    if text is not None:
        path.write_text(text)
    settings = Settings(traffic_cameras_path=path)
    return TestClient(create_app(settings, db_check=_db_ok, jobs=[], start_jobs=False))


def test_traffic_cameras_come_from_the_list_in_order(tmp_path):
    body = (
        _client(
            tmp_path,
            """
- {code: DEK-0668, view: 24030, name: "SR 154 at SR 12", nickname: "Pool Turtle", home: true}
- {code: GDOT-0283, view: 21551, name: "I-285 CCW at US278", nickname: "QT Exit 2"}
""",
        )
        .get("/api/traffic")
        .json()
    )
    assert body["cameras"] == [
        {
            "nickname": "Pool Turtle",
            "name": "SR 154 at SR 12",
            "view": 24030,
            "image_url": "https://511ga.org/map/Cctv/24030",
            "home": True,
        },
        {
            "nickname": "QT Exit 2",
            "name": "I-285 CCW at US278",
            "view": 21551,
            "image_url": "https://511ga.org/map/Cctv/21551",
            "home": False,
        },
    ]


def test_no_list_means_no_traffic_cameras(tmp_path):
    assert _client(tmp_path, None).get("/api/traffic").json() == {"cameras": []}


def test_entries_without_a_numeric_view_are_skipped(tmp_path):
    body = (
        _client(
            tmp_path,
            """
- {code: A, view: "x/../../evil", name: "Bad", nickname: "Bad"}
- {code: B, name: "No view", nickname: "Missing"}
- {code: C, view: 5, name: "Good", nickname: "Good"}
""",
        )
        .get("/api/traffic")
        .json()
    )
    assert [c["nickname"] for c in body["cameras"]] == ["Good"]


LIST = '- {code: DEK-0668, view: 24030, name: "SR 154 at SR 12", nickname: "Pool Turtle"}\n'
STREAM = (
    "https://sfs-msc-pub-lq-02.navigator.dot.ga.gov:443/rtplive/DEK-CCTV-0668/playlist.m3u8"
    "?token=abc.def.ghi"
)
VIDEO_URL = "https://511ga.org/Camera/GetVideoUrl"


@respx.mock
def test_video_gives_the_signed_stream_address(tmp_path):
    route = respx.get(VIDEO_URL).mock(return_value=httpx.Response(200, json=STREAM))
    body = _client(tmp_path, LIST).get("/api/traffic/24030/video").json()
    assert body == {"url": STREAM}
    assert route.calls[0].request.url.params["imageId"] == "24030"


@respx.mock
def test_video_only_for_cameras_on_the_list(tmp_path):
    route = respx.get(VIDEO_URL).mock(return_value=httpx.Response(200, json=STREAM))
    assert _client(tmp_path, LIST).get("/api/traffic/999/video").status_code == 404
    assert not route.called


@respx.mock
def test_video_from_anywhere_but_georgia_dot_is_refused(tmp_path):
    for answer in ["https://evil.example/x.m3u8", "http://x.navigator.dot.ga.gov/p.m3u8", {"a": 1}]:
        respx.get(VIDEO_URL).mock(return_value=httpx.Response(200, json=answer))
        assert _client(tmp_path, LIST).get("/api/traffic/24030/video").status_code == 503


@respx.mock
def test_video_when_511ga_is_down_is_a_503(tmp_path):
    respx.get(VIDEO_URL).mock(side_effect=httpx.ConnectError("down"))
    assert _client(tmp_path, LIST).get("/api/traffic/24030/video").status_code == 503
