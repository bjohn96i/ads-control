import pytest

from adscontrol.refoss.watch import measured_multiplier


def test_measured_multiplier():
    assert measured_multiplier(4500.0, 2250.0) == pytest.approx(2.0)


def test_one_to_one_load_is_about_one():
    assert measured_multiplier(1000.0, 980.0) == pytest.approx(1.02, abs=0.01)


def test_channel_that_did_not_move_is_an_error():
    with pytest.raises(ValueError):
        measured_multiplier(1000.0, 5.0)


def test_unrelated_load_before_the_channel_moves_is_not_counted():
    from adscontrol.refoss.watch import ChangeTracker

    tracker = ChangeTracker()
    tracker.update(0.0, 553.1)
    tracker.update(0.0, 1134.3)  # something else came on
    tracker.update(0.0, 1128.0)
    delta_channel, delta_incoming = tracker.update(434.5, 1853.8)
    assert delta_channel == pytest.approx(434.5)
    assert delta_incoming == pytest.approx(725.8)
    assert measured_multiplier(delta_incoming, delta_channel) == pytest.approx(1.67, abs=0.01)


def test_baseline_holds_once_the_channel_has_moved():
    from adscontrol.refoss.watch import ChangeTracker

    tracker = ChangeTracker()
    tracker.update(0.0, 1000.0)
    tracker.update(500.0, 2000.0)
    assert tracker.update(600.0, 2200.0) == pytest.approx((600.0, 1200.0))
