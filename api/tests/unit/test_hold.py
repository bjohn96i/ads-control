from adscontrol.app import jobs_allowed
from adscontrol.config import Settings


def test_a_hold_file_keeps_the_recorder_idle(tmp_path):
    """The new box deploys before cutover; until the hold file goes, only the Mac records."""
    settings = Settings(hold_path=tmp_path / "hold")
    assert jobs_allowed(settings) is True
    (tmp_path / "hold").touch()
    assert jobs_allowed(settings) is False
