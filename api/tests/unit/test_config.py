from adscontrol.config import Settings


def test_out_of_the_box_the_server_only_answers_to_localhost(monkeypatch):
    """Each install lists its own LAN addresses in ALLOWED_HOSTS; nothing house-specific is built in."""
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    assert Settings(_env_file=None).allowed_hosts == ["localhost"]
