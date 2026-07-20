from datetime import datetime, timezone
from unittest.mock import Mock, call, patch

import pytest

from hedp.configuration import Configuration
from hedp.main import main
from hedp.raw_data import RawData


def test_main_builds_runs_and_closes_in_order() -> None:
    configuration = Configuration(
        base_url="https://example.test",
        station_dn="station-dn",
        username="user",
        password="password",
        database_path="hedp.db",
    )
    raw_data = RawData(
        source="fusionsolar",
        timestamp=datetime(2026, 7, 20, tzinfo=timezone.utc),
        payload={"value": 42},
    )
    calls = Mock()

    with (
        patch("hedp.main.Configuration") as configuration_class,
        patch("hedp.main.FusionSolarClient") as client_class,
        patch("hedp.main.FusionSolarCollector") as collector_class,
        patch("hedp.main.FusionSolarRecordBuilder") as record_builder_class,
        patch("hedp.main.Storage") as storage_class,
        patch("hedp.main.Application") as application_class,
    ):
        client = client_class.return_value
        collector = collector_class.return_value
        record_builder = record_builder_class.return_value
        storage = storage_class.return_value
        connection = storage.connect.return_value
        application = application_class.return_value
        configuration_class.from_environment.return_value = configuration
        application.run.return_value = raw_data
        calls.attach_mock(
            configuration_class.from_environment, "configuration"
        )
        calls.attach_mock(client_class, "client")
        calls.attach_mock(collector_class, "collector")
        calls.attach_mock(record_builder_class, "record_builder")
        calls.attach_mock(storage_class, "storage")
        calls.attach_mock(storage.connect, "connect")
        calls.attach_mock(application_class, "application")
        calls.attach_mock(application.run, "run")
        calls.attach_mock(connection.close, "close")

        result = main()

    assert result is raw_data
    assert calls.mock_calls == [
        call.configuration(),
        call.client(
            base_url="https://example.test",
            station_dn="station-dn",
            username="user",
            password="password",
        ),
        call.collector(client),
        call.record_builder(),
        call.storage("hedp.db"),
        call.connect(),
        call.application(collector, storage, record_builder),
        call.run(),
        call.close(),
    ]
    storage.connect.assert_called_once_with()
    application.run.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_main_closes_connection_when_application_raises() -> None:
    configuration = Configuration(
        base_url="https://example.test",
        station_dn="station-dn",
        username="user",
        password="password",
        database_path="hedp.db",
    )

    with (
        patch("hedp.main.Configuration") as configuration_class,
        patch("hedp.main.FusionSolarClient"),
        patch("hedp.main.FusionSolarCollector"),
        patch("hedp.main.FusionSolarRecordBuilder"),
        patch("hedp.main.Storage") as storage_class,
        patch("hedp.main.Application") as application_class,
    ):
        configuration_class.from_environment.return_value = configuration
        connection = storage_class.return_value.connect.return_value
        application_class.return_value.run.side_effect = RuntimeError("failed")

        with pytest.raises(RuntimeError, match="failed"):
            main()

    connection.close.assert_called_once_with()
