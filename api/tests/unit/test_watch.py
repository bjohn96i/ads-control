import pytest

from adscontrol.refoss.watch import measured_multiplier


def test_measured_multiplier():
    assert measured_multiplier(4500.0, 2250.0) == pytest.approx(2.0)


def test_one_to_one_load_is_about_one():
    assert measured_multiplier(1000.0, 980.0) == pytest.approx(1.02, abs=0.01)


def test_channel_that_did_not_move_is_an_error():
    with pytest.raises(ValueError):
        measured_multiplier(1000.0, 5.0)
