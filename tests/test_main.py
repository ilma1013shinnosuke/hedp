from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock, call, patch

import pytest

from hedp.configuration import Configuration
from hedp.main import cli, main
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


def test_cli_collect_runs_today_and_prints_success(capsys) -> None:
    with patch("hedp.main.main") as main_function:
        cli(["collect"])

    main_function.assert_called_once_with()
    assert capsys.readouterr().out == "Collected 1 RawData item.\n"


def test_cli_backup_uses_storage_only_and_closes_connection(
    tmp_path, capsys
) -> None:
    configuration = Configuration(
        base_url="https://example.test",
        station_dn="station-dn",
        username="user",
        password="password",
        database_path=str(tmp_path / "hedp.db"),
    )

    with (
        patch("hedp.main.Configuration") as configuration_class,
        patch("hedp.main.FusionSolarClient") as client_class,
        patch("hedp.main.FusionSolarCollector") as collector_class,
        patch("hedp.main.FusionSolarRecordBuilder") as builder_class,
        patch("hedp.main.Application") as application_class,
        patch("hedp.main.Storage") as storage_class,
        patch("hedp.main.datetime") as datetime_class,
    ):
        configuration_class.from_environment.return_value = configuration
        datetime_class.now.return_value = datetime(2026, 7, 20, 12, 34, 56)
        storage = storage_class.return_value
        connection = storage.connect.return_value

        cli(["backup"])

    destination = (
        Path(configuration.database_path).resolve().parent
        / "backups"
        / "hedp-20260720-123456.db"
    )
    storage.backup.assert_called_once_with(str(destination))
    connection.close.assert_called_once_with()
    client_class.assert_not_called()
    collector_class.assert_not_called()
    builder_class.assert_not_called()
    application_class.assert_not_called()
    assert capsys.readouterr().out == f"Backup created: {destination}\n"


def test_cli_backup_closes_connection_when_backup_raises(tmp_path) -> None:
    configuration = Configuration(
        base_url="https://example.test",
        station_dn="station-dn",
        username="user",
        password="password",
        database_path=str(tmp_path / "hedp.db"),
    )

    with (
        patch("hedp.main.Configuration") as configuration_class,
        patch("hedp.main.Storage") as storage_class,
    ):
        configuration_class.from_environment.return_value = configuration
        storage = storage_class.return_value
        connection = storage.connect.return_value
        storage.backup.side_effect = RuntimeError("failed")

        with pytest.raises(RuntimeError, match="failed"):
            cli(["backup"])

    connection.close.assert_called_once_with()


def _quality_report(issue_count: int = 0) -> dict[str, object]:
    return {
        "duplicate_records": issue_count,
        "invalid_values": 0,
        "unexpected_metrics": [],
        "unexpected_units": 0,
        "missing_metric_points": [],
        "irregular_intervals": [],
        "summary": {"record_count": 5, "timestamp_count": 1},
    }


@pytest.mark.parametrize(
    ("issue_count", "expected_code", "message"),
    [
        (0, 0, "Quality check passed."),
        (1, 1, "Quality issues found."),
    ],
)
def test_cli_quality_prints_result_and_returns_exit_code(
    issue_count, expected_code, message, capsys
) -> None:
    with patch("hedp.main._quality", return_value=_quality_report(issue_count)):
        result = cli(
            ["quality", "--start", "2026-07-01", "--end", "2026-07-20"]
        )

    assert result == expected_code
    assert capsys.readouterr().out == (
        "Records: 5\n"
        "Timestamps: 1\n"
        f"Duplicate records: {issue_count}\n"
        "Invalid values: 0\n"
        "Unexpected metrics: 0\n"
        "Unexpected units: 0\n"
        "Missing metric points: 0\n"
        "Irregular intervals: 0\n"
        f"{message}\n"
    )


def test_quality_uses_only_sqlite_and_closes_connection(tmp_path) -> None:
    configuration = Configuration(
        base_url="https://example.test",
        station_dn="station-dn",
        username="user",
        password="password",
        database_path=str(tmp_path / "hedp.db"),
    )

    with (
        patch("hedp.main.Configuration") as configuration_class,
        patch("hedp.main.FusionSolarClient") as client_class,
        patch("hedp.main.FusionSolarCollector") as collector_class,
        patch("hedp.main.FusionSolarRecordBuilder") as builder_class,
        patch("hedp.main.Storage") as storage_class,
        patch("hedp.main.Application") as application_class,
    ):
        configuration_class.from_environment.return_value = configuration
        storage = storage_class.return_value
        connection = storage.connect.return_value
        application_class.return_value.check_quality.return_value = (
            _quality_report()
        )

        result = cli(
            ["quality", "--start", "2026-07-01", "--end", "2026-07-20"]
        )

    assert result == 0
    application_class.assert_called_once_with(None, storage, None)
    client_class.assert_not_called()
    collector_class.assert_not_called()
    builder_class.assert_not_called()
    connection.close.assert_called_once_with()


def test_quality_closes_connection_when_check_raises(tmp_path) -> None:
    configuration = Configuration(
        base_url="https://example.test",
        station_dn="station-dn",
        username="user",
        password="password",
        database_path=str(tmp_path / "hedp.db"),
    )

    with (
        patch("hedp.main.Configuration") as configuration_class,
        patch("hedp.main.Storage") as storage_class,
        patch("hedp.main.Application") as application_class,
    ):
        configuration_class.from_environment.return_value = configuration
        connection = storage_class.return_value.connect.return_value
        application_class.return_value.check_quality.side_effect = RuntimeError(
            "failed"
        )

        with pytest.raises(RuntimeError, match="failed"):
            cli(
                [
                    "quality",
                    "--start",
                    "2026-07-01",
                    "--end",
                    "2026-07-20",
                ]
            )

    connection.close.assert_called_once_with()


def test_cli_collects_date_range_and_closes_connection(capsys) -> None:
    application = Mock()
    connection = Mock()
    application.run_range.return_value = [Mock(), Mock(), Mock()]

    with patch(
        "hedp.main._create_application",
        return_value=(application, connection),
    ):
        cli(["collect", "--start", "2026-07-01", "--end", "2026-07-03"])

    application.run_range.assert_called_once_with(
        date(2026, 7, 1), date(2026, 7, 3)
    )
    connection.close.assert_called_once_with()
    assert capsys.readouterr().out == "Collected 3 RawData items.\n"


@pytest.mark.parametrize(
    "arguments",
    [
        ["collect", "--start", "2026-07-01"],
        ["collect", "--end", "2026-07-03"],
        ["collect", "--start", "invalid", "--end", "2026-07-03"],
        ["collect", "--start", "2026-07-03", "--end", "2026-07-01"],
    ],
)
def test_cli_rejects_invalid_date_arguments(arguments) -> None:
    with pytest.raises(SystemExit) as raised:
        cli(arguments)

    assert raised.value.code == 2


def test_cli_closes_connection_when_range_run_raises() -> None:
    application = Mock()
    connection = Mock()
    application.run_range.side_effect = RuntimeError("failed")

    with patch(
        "hedp.main._create_application",
        return_value=(application, connection),
    ):
        with pytest.raises(RuntimeError, match="failed"):
            cli(
                [
                    "collect",
                    "--start",
                    "2026-07-01",
                    "--end",
                    "2026-07-03",
                ]
            )

    connection.close.assert_called_once_with()


def test_cli_missing_prints_dates_and_count(capsys) -> None:
    application = Mock()
    connection = Mock()
    application.find_missing_dates.return_value = [
        date(2026, 7, 2),
        date(2026, 7, 4),
    ]

    with patch(
        "hedp.main._create_application",
        return_value=(application, connection),
    ):
        cli(["missing", "--start", "2026-07-01", "--end", "2026-07-05"])

    assert capsys.readouterr().out == (
        "2026-07-02\n2026-07-04\nMissing 2 date(s).\n"
    )
    connection.close.assert_called_once_with()


def test_cli_missing_prints_no_missing_dates(capsys) -> None:
    application = Mock()
    connection = Mock()
    application.find_missing_dates.return_value = []

    with patch(
        "hedp.main._create_application",
        return_value=(application, connection),
    ):
        cli(["missing", "--start", "2026-07-01", "--end", "2026-07-05"])

    assert capsys.readouterr().out == "No missing dates.\nMissing 0 date(s).\n"


def test_cli_backfill_missing_prints_count(capsys) -> None:
    application = Mock()
    connection = Mock()
    application.backfill_missing.return_value = [Mock(), Mock()]

    with patch(
        "hedp.main._create_application",
        return_value=(application, connection),
    ):
        cli(
            [
                "backfill-missing",
                "--start",
                "2026-07-01",
                "--end",
                "2026-07-05",
            ]
        )

    assert capsys.readouterr().out == "Backfilled 2 RawData item(s).\n"
    connection.close.assert_called_once_with()


@pytest.mark.parametrize("command", ["missing", "backfill-missing"])
def test_cli_new_commands_reject_invalid_arguments(command) -> None:
    with pytest.raises(SystemExit) as raised:
        cli([command, "--start", "2026-07-05", "--end", "2026-07-01"])

    assert raised.value.code == 2


def test_cli_backfill_closes_connection_when_run_raises() -> None:
    application = Mock()
    connection = Mock()
    application.backfill_missing.side_effect = RuntimeError("failed")

    with patch(
        "hedp.main._create_application",
        return_value=(application, connection),
    ):
        with pytest.raises(RuntimeError, match="failed"):
            cli(
                [
                    "backfill-missing",
                    "--start",
                    "2026-07-01",
                    "--end",
                    "2026-07-05",
                ]
            )

    connection.close.assert_called_once_with()
