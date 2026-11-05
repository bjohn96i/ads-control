from datetime import datetime, timezone

import pytest
import typer

from adscontrol.cli import parse_since


def test_since_keeps_its_time_zone():
    assert parse_since("2026-11-05T03:20:00+00:00") == datetime(
        2026, 11, 5, 3, 20, tzinfo=timezone.utc
    )


def test_since_without_a_zone_is_refused():
    """A bare time would be read in the database server's zone, shifting the final pass by hours."""
    with pytest.raises(typer.BadParameter):
        parse_since("2026-11-05T03:20:00")
