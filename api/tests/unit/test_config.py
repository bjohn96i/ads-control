from adscontrol.config import Settings


def test_out_of_the_box_the_server_only_answers_to_localhost(monkeypatch):
    """Each install lists its own LAN addresses in ALLOWED_HOSTS; nothing house-specific is built in."""
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    assert Settings(_env_file=None).allowed_hosts == ["localhost"]


def test_a_blank_stack_variable_falls_back_to_its_default(monkeypatch):
    """Compose passes an unset ${VAR} as an empty string; optional settings must survive that."""
    for name in ("HOUSEHOLD", "ALLOWED_HOSTS", "WEATHER_LAT", "WEATHER_LON", "REFOSS_HOST"):
        monkeypatch.setenv(name, "")
    settings = Settings(_env_file=None)
    assert settings.household == []
    assert settings.allowed_hosts == ["localhost"]
    assert settings.weather_lat is None
    assert settings.refoss_host == "192.168.4.254"
