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
            "image_url": "https://511ga.org/map/Cctv/24030",
            "home": True,
        },
        {
            "nickname": "QT Exit 2",
            "name": "I-285 CCW at US278",
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
