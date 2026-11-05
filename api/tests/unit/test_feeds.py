from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from adscontrol.api.health import stopped_since
from adscontrol.scheduler import SourceState


def _request(states):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(source_states=states)))


def test_a_failing_feed_says_when_it_last_worked():
    state = SourceState(
        5,
        last_success=datetime.now(timezone.utc) - timedelta(minutes=10),
        last_error="RefreshError: x",
    )
    assert stopped_since(_request({"camera_events": state}), "camera_events") == {
        "since": state.last_success
    }


def test_a_feed_that_never_worked_is_stopped_with_no_time():
    state = SourceState(5, last_error="RefreshError: x")
    assert stopped_since(_request({"camera_events": state}), "camera_events") == {"since": None}


def test_one_blip_or_a_feed_still_starting_is_not_stopped():
    blip = SourceState(
        5, last_success=datetime.now(timezone.utc) - timedelta(seconds=6), last_error="Timeout"
    )
    starting = SourceState(5)
    assert stopped_since(_request({"camera_events": blip}), "camera_events") is None
    assert stopped_since(_request({"camera_events": starting}), "camera_events") is None
    assert stopped_since(_request({}), "camera_events") is None
