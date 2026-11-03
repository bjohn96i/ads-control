import pytest

from adscontrol.cameras.frame import still_frame


def test_preview_clip_becomes_a_jpeg(tiny_mp4):
    image = still_frame(tiny_mp4)
    assert image[:2] == b"\xff\xd8" and image[-2:] == b"\xff\xd9"


def test_unreadable_clip_is_a_value_error():
    with pytest.raises(ValueError):
        still_frame(b"not a video")
