import pytest

from hedp.configuration import Configuration


def test_device_dns_are_trimmed_deduplicated_and_ordered(monkeypatch):
    monkeypatch.setenv(
        "HEDP_FUSIONSOLAR_DEVICE_DNS", " NE=2,NE=1,,NE=2 "
    )
    assert Configuration.device_dns_from_environment() == ["NE=2", "NE=1"]


def test_sumicore_device_dns_take_priority_over_legacy_value(monkeypatch):
    monkeypatch.setenv("SUMICORE_FUSIONSOLAR_DEVICE_DNS", "NE=new")
    monkeypatch.setenv("HEDP_FUSIONSOLAR_DEVICE_DNS", "NE=legacy")
    assert Configuration.device_dns_from_environment() == ["NE=new"]


def test_device_dns_must_be_configured(monkeypatch):
    monkeypatch.delenv("SUMICORE_FUSIONSOLAR_DEVICE_DNS", raising=False)
    monkeypatch.delenv("HEDP_FUSIONSOLAR_DEVICE_DNS", raising=False)
    with pytest.raises(RuntimeError, match="HEDP_FUSIONSOLAR_DEVICE_DNS"):
        Configuration.device_dns_from_environment()


def test_battery_dc_configuration(monkeypatch):
    monkeypatch.setenv("HEDP_FUSIONSOLAR_BATTERY_DN", " NE=1 ")
    monkeypatch.setenv("HEDP_FUSIONSOLAR_BATTERY_SIGIDS", " 1,2 ")
    assert Configuration.battery_dc_from_environment() == ("NE=1", "1,2")


def test_battery_dc_configuration_requires_both_values(monkeypatch):
    monkeypatch.delenv("SUMICORE_FUSIONSOLAR_BATTERY_DN", raising=False)
    monkeypatch.delenv("SUMICORE_FUSIONSOLAR_BATTERY_SIGIDS", raising=False)
    monkeypatch.delenv("HEDP_FUSIONSOLAR_BATTERY_DN", raising=False)
    monkeypatch.delenv("HEDP_FUSIONSOLAR_BATTERY_SIGIDS", raising=False)
    with pytest.raises(RuntimeError, match="HEDP_FUSIONSOLAR_BATTERY_DN"):
        Configuration.battery_dc_from_environment()


def test_battery_dc_rejects_missing_device(monkeypatch):
    monkeypatch.delenv("SUMICORE_FUSIONSOLAR_BATTERY_DN", raising=False)
    monkeypatch.delenv("HEDP_FUSIONSOLAR_BATTERY_DN", raising=False)
    monkeypatch.setenv("HEDP_FUSIONSOLAR_BATTERY_SIGIDS", "1,2")
    with pytest.raises(RuntimeError, match="HEDP_FUSIONSOLAR_BATTERY_DN"):
        Configuration.battery_dc_from_environment()


ENVIRONMENT = {
    "HEDP_FUSIONSOLAR_BASE_URL": "https://example.test",
    "HEDP_FUSIONSOLAR_STATION_DN": "station-dn",
    "HEDP_FUSIONSOLAR_USERNAME": "user",
    "HEDP_FUSIONSOLAR_PASSWORD": "password",
    "HEDP_DATABASE_PATH": "hedp.db",
}


def set_environment(monkeypatch) -> None:
    for name, value in ENVIRONMENT.items():
        monkeypatch.setenv(name, value)


def test_from_environment() -> None:
    with pytest.MonkeyPatch.context() as monkeypatch:
        set_environment(monkeypatch)

        configuration = Configuration.from_environment()

    assert configuration == Configuration(
        base_url="https://example.test",
        station_dn="station-dn",
        username="user",
        password="password",
        database_path="hedp.db",
    )


def test_from_environment_accepts_sumicore_names() -> None:
    with pytest.MonkeyPatch.context() as monkeypatch:
        for name, value in ENVIRONMENT.items():
            monkeypatch.delenv(name, raising=False)
            monkeypatch.setenv(name.replace("HEDP_", "SUMICORE_"), value)

        configuration = Configuration.from_environment()

    assert configuration.database_path == "hedp.db"
    assert configuration.station_dn == "station-dn"


@pytest.mark.parametrize("missing_name", ENVIRONMENT)
def test_from_environment_rejects_each_missing_variable(missing_name) -> None:
    with pytest.MonkeyPatch.context() as monkeypatch:
        set_environment(monkeypatch)
        monkeypatch.delenv(missing_name)
        monkeypatch.delenv(missing_name.replace("HEDP_", "SUMICORE_"), raising=False)

        with pytest.raises(RuntimeError, match=missing_name):
            Configuration.from_environment()


def test_from_environment_rejects_empty_value() -> None:
    with pytest.MonkeyPatch.context() as monkeypatch:
        set_environment(monkeypatch)
        monkeypatch.delenv("SUMICORE_FUSIONSOLAR_USERNAME", raising=False)
        monkeypatch.setenv("HEDP_FUSIONSOLAR_USERNAME", "")

        with pytest.raises(RuntimeError, match="HEDP_FUSIONSOLAR_USERNAME"):
            Configuration.from_environment()
