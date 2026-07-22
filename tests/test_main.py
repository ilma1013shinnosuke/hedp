import json
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock, call, patch
from zoneinfo import ZoneInfo

import pytest

from hedp.configuration import Configuration
from hedp.main import cli, main
from hedp.storage import RawData


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


def test_cli_collect_energy_balance_runs_today_in_tokyo(capsys) -> None:
    application = Mock()
    connection = Mock()

    with (
        patch(
            "hedp.main._create_energy_balance_application",
            return_value=(application, connection),
        ),
        patch("hedp.main.datetime") as datetime_class,
    ):
        datetime_class.now.return_value = datetime(
            2026, 7, 21, 8, 30, tzinfo=ZoneInfo("Asia/Tokyo")
        )
        result = cli(["collect-energy-balance"])

    assert result is None
    application.run_energy_balance_for_date.assert_called_once_with(
        date(2026, 7, 21)
    )
    connection.close.assert_called_once_with()
    assert capsys.readouterr().out == (
        "Collected 1 energy-balance RawData item(s).\n"
    )


def test_cli_collect_energy_balance_runs_date_range(capsys) -> None:
    application = Mock()
    connection = Mock()
    application.run_energy_balance_range.return_value = [Mock(), Mock()]

    with patch(
        "hedp.main._create_energy_balance_application",
        return_value=(application, connection),
    ):
        cli(
            [
                "collect-energy-balance",
                "--start",
                "2026-07-20",
                "--end",
                "2026-07-21",
            ]
        )

    application.run_energy_balance_range.assert_called_once_with(
        date(2026, 7, 20), date(2026, 7, 21)
    )
    connection.close.assert_called_once_with()
    assert capsys.readouterr().out == (
        "Collected 2 energy-balance RawData item(s).\n"
    )


def test_cli_collect_battery_dc(capsys):
    application = Mock()
    connection = Mock()
    application.run_battery_dc.return_value = ([Mock()] * 4, [])
    with patch(
        "hedp.main._create_battery_dc_application",
        return_value=(application, connection),
    ):
        result = cli(
            [
                "collect-battery-dc",
                "--device-dn",
                "NE=1",
                "--sigids",
                "1,2",
            ]
        )
    assert result == 0
    application.run_battery_dc.assert_called_once_with(
        "NE=1", "1,2", [1, 2, 3, 4]
    )
    connection.close.assert_called_once_with()
    assert capsys.readouterr().out == (
        "Collected 4 battery-dc RawData item(s). Failed 0.\n"
    )


def test_cli_collect_alarm_history(capsys):
    application = Mock()
    connection = Mock()
    application.run_alarm_history.return_value = ([Mock()], [])
    with (
        patch(
            "hedp.main._create_alarm_application",
            return_value=(application, connection),
        ),
        patch(
            "hedp.main.Configuration.device_dns_from_environment",
            return_value=["NE=1"],
        ),
    ):
        result = cli(
            [
                "collect-alarms-history",
                "--start",
                "2026-07-19",
                "--end",
                "2026-07-20",
            ]
        )
    assert result == 0
    application.run_alarm_history.assert_called_once_with(
        ["NE=1"], date(2026, 7, 19), date(2026, 7, 20)
    )
    connection.close.assert_called_once_with()
    assert capsys.readouterr().out == (
        "Collected 1 alarm-history RawData item(s). Failed 0.\n"
    )


def test_cli_quality_alarms_returns_issue_status(capsys):
    configuration = Configuration(
        "https://example.test", "station", "user", "password", "hedp.db"
    )
    with (
        patch("hedp.main.Configuration") as configuration_class,
        patch("hedp.main.Storage") as storage_class,
        patch("hedp.main.Application") as application_class,
    ):
        configuration_class.from_environment.return_value = configuration
        configuration_class.device_dns_from_environment.return_value = ["NE=1"]
        application_class.return_value.check_alarm_quality.return_value = {
            "collection_count": 1,
            "invalid_responses": 0,
            "total_hits": 0,
            "issue_count": 1,
        }
        result = cli(["quality-alarms"])
    assert result == 1
    storage_class.return_value.connect.return_value.close.assert_called_once()
    assert capsys.readouterr().out == (
        "Collections: 1\nInvalid responses: 0\n"
        "Alarm hits: 0\nQuality issues: 1\n"
    )


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


def test_cli_quality_diagnose_prints_details_without_fusionsolar(
    tmp_path, capsys
) -> None:
    configuration = Configuration(
        base_url="https://example.test",
        station_dn="station-dn",
        username="user",
        password="password",
        database_path=str(tmp_path / "hedp.db"),
    )
    diagnosis = {
        "missing_metrics_by_metric": {"buyPower": 2},
        "missing_combinations": [
            {"missing_metrics": ["buyPower", "powerProfit"], "count": 2}
        ],
        "missing_by_hour": {"0": 2},
        "missing_by_month": {"2026-01": 2},
        "missing_examples": [
            {
                "timestamp": "2026-01-01T00:00:00+09:00",
                "missing_metrics": ["buyPower", "powerProfit"],
            }
        ],
        "irregular_intervals_by_minutes": {10.0: 1},
        "irregular_intervals_shorter_than_5_minutes": 0,
        "irregular_intervals_longer_than_5_minutes": 1,
        "irregular_intervals_by_hour": {"0": 1},
        "irregular_intervals_by_month": {"2026-01": 1},
        "irregular_interval_examples": [
            {
                "previous": "2026-01-01T00:00:00+09:00",
                "current": "2026-01-01T00:10:00+09:00",
                "minutes": 10.0,
            }
        ],
    }

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
        application_class.return_value.diagnose_quality.return_value = diagnosis

        result = cli(
            [
                "quality-diagnose",
                "--start",
                "2026-01-01",
                "--end",
                "2026-01-31",
            ]
        )

    output = capsys.readouterr().out
    assert result == 0
    assert "Missing metrics by metric:\n  buyPower: 2\n" in output
    assert "Missing combinations (top 10):" in output
    assert "Missing points by hour:" in output
    assert "Missing points by month:" in output
    assert "Missing examples (first 20):" in output
    assert "Irregular intervals by minutes (top 20):" in output
    assert "Irregular intervals shorter than 5 minutes: 0" in output
    assert "Irregular intervals longer than 5 minutes: 1" in output
    assert "Irregular intervals by hour:" in output
    assert "Irregular intervals by month:" in output
    assert "Irregular interval examples (first 20):" in output
    application_class.assert_called_once_with(None, storage, None)
    client_class.assert_not_called()
    collector_class.assert_not_called()
    builder_class.assert_not_called()
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


def _daily_health_report(status="ok"):
    return {
        "status": status,
        "checked_at": "2026-07-21T03:20:00+09:00",
        "window_start": "2026-07-20T03:20:00+09:00",
        "window_end": "2026-07-21T03:20:00+09:00",
        "warnings": [] if status == "ok" else [{
            "source": "backup",
            "subject": None,
            "problem": "recent backup is missing",
            "latest_timestamp": None,
            "expected": "< 48h",
            "actual": None,
        }],
        "critical": [],
        "source_summaries": {},
        "backup_summary": {},
        "database_summary": {},
    }


def test_cli_daily_health_json_is_reproducible_and_closes(capsys) -> None:
    connection = Mock()
    service = Mock()
    service.check.return_value = _daily_health_report()
    with (
        patch(
            "hedp.main.Configuration.database_path_from_environment",
            return_value="hedp.db",
        ),
        patch(
            "hedp.main.Configuration.device_dns_from_environment",
            return_value=["device-1"],
        ),
        patch("hedp.main.Storage") as storage_class,
        patch("hedp.main.DailyHealthService", return_value=service),
        patch("hedp.main.FusionSolarClient") as client_class,
    ):
        storage_class.return_value.connect_readonly.return_value = connection
        result = cli([
            "daily-health", "--at", "2026-07-21T03:20:00+09:00",
            "--hours", "12", "--json",
        ])

    assert result == 0
    checked_at = service.check.call_args.args[0]
    assert checked_at.isoformat() == "2026-07-21T03:20:00+09:00"
    assert service.check.call_args.args[1] == 12
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
    connection.close.assert_called_once_with()
    client_class.assert_not_called()


def test_cli_daily_health_warning_exit_and_display(capsys) -> None:
    service = Mock()
    service.check.return_value = _daily_health_report("warning")
    with (
        patch(
            "hedp.main.Configuration.database_path_from_environment",
            return_value="hedp.db",
        ),
        patch(
            "hedp.main.Configuration.device_dns_from_environment",
            return_value=["device-1"],
        ),
        patch("hedp.main.Storage") as storage_class,
        patch("hedp.main.DailyHealthService", return_value=service),
    ):
        result = cli(["daily-health", "--verbose"])

    assert result == 1
    assert "HEDP daily health: WARNING" in capsys.readouterr().out
    storage_class.return_value.connect_readonly.return_value.close.assert_called_once()


def test_cli_daily_health_database_failure_returns_critical(capsys) -> None:
    with (
        patch(
            "hedp.main.Configuration.database_path_from_environment",
            return_value="missing.db",
        ),
        patch(
            "hedp.main.Configuration.device_dns_from_environment",
            return_value=["device-1"],
        ),
        patch("hedp.main.Storage") as storage_class,
    ):
        storage_class.return_value.connect_readonly.side_effect = OSError(
            "secret detail"
        )
        result = cli(["daily-health", "--json"])

    output = capsys.readouterr().out
    assert result == 2
    assert json.loads(output)["status"] == "critical"
    assert "secret detail" not in output


def test_cli_daily_health_rejects_naive_at() -> None:
    with pytest.raises(SystemExit) as raised:
        cli(["daily-health", "--at", "2026-07-21T03:20:00"])
    assert raised.value.code == 2
