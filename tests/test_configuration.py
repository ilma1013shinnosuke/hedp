import pytest

from hedp.configuration import Configuration


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


@pytest.mark.parametrize("missing_name", ENVIRONMENT)
def test_from_environment_rejects_each_missing_variable(missing_name) -> None:
    with pytest.MonkeyPatch.context() as monkeypatch:
        set_environment(monkeypatch)
        monkeypatch.delenv(missing_name)

        with pytest.raises(RuntimeError, match=missing_name):
            Configuration.from_environment()


def test_from_environment_rejects_empty_value() -> None:
    with pytest.MonkeyPatch.context() as monkeypatch:
        set_environment(monkeypatch)
        monkeypatch.setenv("HEDP_FUSIONSOLAR_USERNAME", "")

        with pytest.raises(RuntimeError, match="HEDP_FUSIONSOLAR_USERNAME"):
            Configuration.from_environment()
