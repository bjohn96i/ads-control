from fastapi.testclient import TestClient

from adscontrol.app import create_app
from adscontrol.config import Settings


def _client(tmp_path) -> TestClient:
    (tmp_path / "index.html").write_text("<title>page</title>")
    (tmp_path / "house.svg").write_text("<svg/>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "a.js").write_text("js")
    return TestClient(create_app(Settings(), jobs=[], start_jobs=False, web_dir=tmp_path))


def test_root_and_deep_links_get_the_page(tmp_path):
    client = _client(tmp_path)
    assert "page" in client.get("/").text
    assert "page" in client.get("/energy").text


def test_built_files_are_served(tmp_path):
    client = _client(tmp_path)
    assert client.get("/house.svg").text == "<svg/>"
    assert client.get("/assets/a.js").text == "js"


def test_unknown_api_path_is_404_not_the_page(tmp_path):
    assert _client(tmp_path).get("/api/nope").status_code == 404


def test_path_traversal_gets_the_page_not_the_file(tmp_path):
    (tmp_path.parent / "secret.txt").write_text("secret")
    assert "secret" not in _client(tmp_path).get("/..%2Fsecret.txt").text
