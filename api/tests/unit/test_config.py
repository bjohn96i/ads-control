import pytest

from adscontrol.config import MisenteredSetting, Settings


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


def test_a_value_pasted_with_its_own_name_is_refused(monkeypatch):
    """Portainer once got REFOSS_HOST=REFOSS_HOST=192.168.4.254; fail at start, not silently later."""
    monkeypatch.setenv("REFOSS_HOST", "REFOSS_HOST=192.168.4.254")
    with pytest.raises(MisenteredSetting, match="REFOSS_HOST"):
        Settings(_env_file=None)


@pytest.mark.parametrize("host", ["192.168.4.254", "refoss.local", "em16"])
def test_a_plain_address_or_name_is_accepted(host):
    assert Settings(_env_file=None, refoss_host=host).refoss_host == host


@pytest.mark.parametrize("host", ["http://192.168.4.254", "192.168.4.254 ", "a b", "x=y"])
def test_a_malformed_monitor_address_is_refused(host):
    with pytest.raises(ValueError):
        Settings(_env_file=None, refoss_host=host)
