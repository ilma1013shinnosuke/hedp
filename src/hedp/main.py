import argparse
import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from hedp.application import Application
from hedp.configuration import Configuration
from hedp.daily_health import DailyHealthService
from hedp.adapters.fusionsolar.client import FusionSolarClient
from hedp.adapters.fusionsolar.alarm_collector import FusionSolarAlarmCollector
from hedp.adapters.fusionsolar.battery_dc_collector import (
    FusionSolarBatteryDcCollector,
)
from hedp.adapters.fusionsolar.station_collector import FusionSolarCollector
from hedp.adapters.fusionsolar.energy_balance_collector import (
    FusionSolarEnergyBalanceCollector,
)
from hedp.adapters.fusionsolar.device_realtime_collector import (
    FusionSolarDeviceRealtimeCollector,
)
from hedp.adapters.fusionsolar.energy_balance_record_builder import (
    FusionSolarEnergyBalanceRecordBuilder,
)
from hedp.adapters.fusionsolar.record_builder import FusionSolarRecordBuilder
from hedp.adapters.fusionsolar.report_importer import FusionSolarReportImporter
from hedp.adapters.fusionsolar.gas_queue_importer import (
    FusionSolarGasQueueImporter,
)
from hedp.storage import RawData
from hedp.storage import Storage
from hedp.adapters.switchbot.cli import add_switchbot_parser, run_switchbot


def _create_application() -> tuple[Application, sqlite3.Connection]:
    configuration = Configuration.from_environment()
    client = FusionSolarClient(
        base_url=configuration.base_url,
        station_dn=configuration.station_dn,
        username=configuration.username,
        password=configuration.password,
    )
    collector = FusionSolarCollector(client)
    record_builder = FusionSolarRecordBuilder()
    storage = Storage(configuration.database_path)
    connection = storage.connect()
    try:
        application = Application(collector, storage, record_builder)
    except Exception:
        connection.close()
        raise
    return application, connection


def _create_energy_balance_application() -> tuple[
    Application, sqlite3.Connection
]:
    configuration = Configuration.from_environment()
    client = FusionSolarClient(
        base_url=configuration.base_url,
        station_dn=configuration.station_dn,
        username=configuration.username,
        password=configuration.password,
    )
    collector = FusionSolarEnergyBalanceCollector(client)
    storage = Storage(configuration.database_path)
    connection = storage.connect()
    try:
        application = Application(
            None,
            storage,
            None,
            collector,
            energy_balance_record_builder=FusionSolarEnergyBalanceRecordBuilder(),
        )
    except Exception:
        connection.close()
        raise
    return application, connection


def _create_device_realtime_application() -> tuple[
    Application, sqlite3.Connection
]:
    configuration = Configuration.from_environment()
    client = FusionSolarClient(
        base_url=configuration.base_url,
        station_dn=configuration.station_dn,
        username=configuration.username,
        password=configuration.password,
    )
    storage = Storage(configuration.database_path)
    connection = storage.connect()
    application = Application(
        None,
        storage,
        None,
        device_realtime_collector=FusionSolarDeviceRealtimeCollector(client),
    )
    return application, connection


def _create_battery_dc_application() -> tuple[
    Application, sqlite3.Connection
]:
    configuration = Configuration.from_environment()
    client = FusionSolarClient(
        base_url=configuration.base_url,
        station_dn=configuration.station_dn,
        username=configuration.username,
        password=configuration.password,
    )
    storage = Storage(configuration.database_path)
    connection = storage.connect()
    application = Application(
        None,
        storage,
        None,
        battery_dc_collector=FusionSolarBatteryDcCollector(client),
    )
    return application, connection


def _create_alarm_application() -> tuple[Application, sqlite3.Connection]:
    configuration = Configuration.from_environment()
    client = FusionSolarClient(
        base_url=configuration.base_url,
        station_dn=configuration.station_dn,
        username=configuration.username,
        password=configuration.password,
    )
    storage = Storage(configuration.database_path)
    connection = storage.connect()
    application = Application(
        None,
        storage,
        None,
        alarm_collector=FusionSolarAlarmCollector(client),
    )
    return application, connection


def _create_realtime_application() -> tuple[Application, sqlite3.Connection]:
    configuration = Configuration.from_environment()
    client = FusionSolarClient(
        base_url=configuration.base_url,
        station_dn=configuration.station_dn,
        username=configuration.username,
        password=configuration.password,
    )
    storage = Storage(configuration.database_path)
    connection = storage.connect()
    application = Application(
        None,
        storage,
        None,
        device_realtime_collector=FusionSolarDeviceRealtimeCollector(client),
        battery_dc_collector=FusionSolarBatteryDcCollector(client),
        alarm_collector=FusionSolarAlarmCollector(client),
    )
    return application, connection


def main() -> RawData:
    application, connection = _create_application()
    try:
        return application.run()
    finally:
        connection.close()


def _date_argument(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "date must use YYYY-MM-DD format"
        ) from error
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD format")
    return parsed


def _datetime_argument(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "datetime must use ISO 8601 format"
        ) from error
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError(
            "datetime must include a timezone offset"
        )
    return parsed


def _backup() -> Path:
    configuration = Configuration.from_environment()
    storage = Storage(configuration.database_path)
    connection = storage.connect()
    try:
        database_path = Path(configuration.database_path).resolve()
        timestamp = datetime.now(ZoneInfo("Asia/Tokyo")).strftime(
            "%Y%m%d-%H%M%S"
        )
        destination = (
            database_path.parent
            / "backups"
            / f"hedp-{timestamp}.db"
        )
        storage.backup(str(destination))
    finally:
        connection.close()
    return destination


def _quality(start_date: date, end_date: date) -> dict[str, object]:
    configuration = Configuration.from_environment()
    storage = Storage(configuration.database_path)
    connection = storage.connect()
    try:
        application = Application(None, storage, None)
        return application.check_quality(start_date, end_date)
    finally:
        connection.close()


def _quality_diagnose(start_date: date, end_date: date) -> dict[str, object]:
    configuration = Configuration.from_environment()
    storage = Storage(configuration.database_path)
    connection = storage.connect()
    try:
        application = Application(None, storage, None)
        return application.diagnose_quality(start_date, end_date)
    finally:
        connection.close()


def _print_counts(counts: dict, limit: Optional[int] = None) -> None:
    items = list(counts.items())
    if limit is not None:
        items = sorted(items, key=lambda item: (-item[1], item[0]))[:limit]
    if not items:
        print("  None")
    for key, count in items:
        print(f"  {key}: {count}")


def _print_quality_diagnosis(diagnosis: dict[str, object]) -> None:
    print("Missing metrics by metric:")
    _print_counts(diagnosis["missing_metrics_by_metric"])
    print("Missing combinations (top 10):")
    combinations = diagnosis["missing_combinations"][:10]
    if not combinations:
        print("  None")
    for combination in combinations:
        metrics = ", ".join(combination["missing_metrics"])
        print(f"  {metrics}: {combination['count']}")
    print("Missing points by hour:")
    _print_counts(diagnosis["missing_by_hour"])
    print("Missing points by month:")
    _print_counts(diagnosis["missing_by_month"])
    print("Missing examples (first 20):")
    missing_examples = diagnosis["missing_examples"]
    if not missing_examples:
        print("  None")
    for example in missing_examples:
        metrics = ", ".join(example["missing_metrics"])
        print(f"  {example['timestamp']}: {metrics}")

    print("Irregular intervals by minutes (top 20):")
    _print_counts(diagnosis["irregular_intervals_by_minutes"], limit=20)
    print(
        "Irregular intervals shorter than 5 minutes: "
        f"{diagnosis['irregular_intervals_shorter_than_5_minutes']}"
    )
    print(
        "Irregular intervals longer than 5 minutes: "
        f"{diagnosis['irregular_intervals_longer_than_5_minutes']}"
    )
    print("Irregular intervals by hour:")
    _print_counts(diagnosis["irregular_intervals_by_hour"])
    print("Irregular intervals by month:")
    _print_counts(diagnosis["irregular_intervals_by_month"])
    print("Irregular interval examples (first 20):")
    interval_examples = diagnosis["irregular_interval_examples"]
    if not interval_examples:
        print("  None")
    for example in interval_examples:
        print(
            f"  {example['previous']} -> {example['current']}: "
            f"{example['minutes']} minutes"
        )


def _print_daily_health(report: dict[str, object], verbose: bool) -> None:
    status = str(report["status"]).upper()
    print(f"HEDP daily health: {status}")
    print(
        f"Checked window: {report['window_start']} - {report['window_end']}"
    )
    summaries = report["source_summaries"]
    print(f"RawData sources: {len(summaries)}")
    print(f"Warnings: {len(report['warnings'])}")
    print(f"Critical: {len(report['critical'])}")
    issues = [*report["critical"], *report["warnings"]]
    for issue in issues:
        subject = f" ({issue['subject']})" if issue["subject"] else ""
        print(f"- {issue['source']}{subject}: {issue['problem']}")
        print(
            f"  latest={issue['latest_timestamp']} "
            f"expected={issue['expected']} actual={issue['actual']}"
        )
    if verbose:
        for source, summary in summaries.items():
            print(
                f"- {source}: count={summary['count']} "
                f"latest={summary['latest_timestamp']} "
                f"age_seconds={summary['seconds_since_latest']}"
            )
        database = report["database_summary"]
        backup = report["backup_summary"]
        if database:
            print(
                f"- database: integrity={database['integrity']} "
                f"size={database['size_bytes']} "
                f"raw={database['raw_data_count']} "
                f"records={database['record_count']}"
            )
        if backup:
            print(
                f"- backup: latest={backup['latest_timestamp']} "
                f"age_hours={backup['age_hours']}"
            )


def cli(argv: Optional[list[str]] = None) -> Optional[int]:
    parser = argparse.ArgumentParser(prog="hedp")
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect_parser = subparsers.add_parser("collect")
    collect_parser.add_argument("--start", type=_date_argument)
    collect_parser.add_argument("--end", type=_date_argument)
    energy_balance_parser = subparsers.add_parser("collect-energy-balance")
    energy_balance_parser.add_argument("--start", type=_date_argument)
    energy_balance_parser.add_argument("--end", type=_date_argument)
    device_parser = subparsers.add_parser("collect-device-realtime")
    device_group = device_parser.add_mutually_exclusive_group()
    device_group.add_argument("--all", action="store_true")
    device_group.add_argument("--device-dn")
    subparsers.add_parser("collect-realtime")
    battery_parser = subparsers.add_parser("collect-battery-dc")
    battery_parser.add_argument("--device-dn")
    battery_parser.add_argument("--sigids")
    battery_parser.add_argument("--module-id", type=int, action="append")
    current_alarm_parser = subparsers.add_parser("collect-alarms-current")
    current_alarm_group = current_alarm_parser.add_mutually_exclusive_group()
    current_alarm_group.add_argument("--all", action="store_true")
    current_alarm_group.add_argument("--device-dn")
    history_alarm_parser = subparsers.add_parser("collect-alarms-history")
    history_alarm_parser.add_argument(
        "--start", type=_date_argument, required=True
    )
    history_alarm_parser.add_argument(
        "--end", type=_date_argument, required=True
    )
    history_alarm_group = history_alarm_parser.add_mutually_exclusive_group()
    history_alarm_group.add_argument("--all", action="store_true")
    history_alarm_group.add_argument("--device-dn")
    build_energy_parser = subparsers.add_parser("build-energy-balance-records")
    build_energy_parser.add_argument("--start", type=_date_argument, required=True)
    build_energy_parser.add_argument("--end", type=_date_argument, required=True)
    energy_quality_parser = subparsers.add_parser("quality-energy-balance")
    energy_quality_parser.add_argument("--start", type=_date_argument, required=True)
    energy_quality_parser.add_argument("--end", type=_date_argument, required=True)
    energy_backfill_parser = subparsers.add_parser("backfill-energy-balance")
    energy_backfill_parser.add_argument("--start", type=_date_argument, required=True)
    energy_backfill_parser.add_argument("--end", type=_date_argument, required=True)
    subparsers.add_parser("diagnose-device-realtime")
    subparsers.add_parser("quality-battery-dc")
    subparsers.add_parser("diagnose-battery-dc")
    subparsers.add_parser("quality-alarms")
    subparsers.add_parser("diagnose-alarms")
    missing_parser = subparsers.add_parser("missing")
    missing_parser.add_argument("--start", type=_date_argument, required=True)
    missing_parser.add_argument("--end", type=_date_argument, required=True)
    backfill_parser = subparsers.add_parser("backfill-missing")
    backfill_parser.add_argument("--start", type=_date_argument, required=True)
    backfill_parser.add_argument("--end", type=_date_argument, required=True)
    subparsers.add_parser("backup")
    report_import_parser = subparsers.add_parser("import-fusionsolar-reports")
    report_import_parser.add_argument("path", type=Path)
    report_import_parser.add_argument("--inspect", action="store_true")
    report_import_parser.add_argument("--dry-run", action="store_true")
    gas_import_parser = subparsers.add_parser("import-fusionsolar-gas-queue")
    gas_import_parser.add_argument("path", type=Path)
    gas_import_group = gas_import_parser.add_mutually_exclusive_group()
    gas_import_group.add_argument("--inspect", action="store_true")
    gas_import_group.add_argument("--dry-run", action="store_true")
    quality_parser = subparsers.add_parser("quality")
    quality_parser.add_argument("--start", type=_date_argument, required=True)
    quality_parser.add_argument("--end", type=_date_argument, required=True)
    diagnose_parser = subparsers.add_parser("quality-diagnose")
    diagnose_parser.add_argument("--start", type=_date_argument, required=True)
    diagnose_parser.add_argument("--end", type=_date_argument, required=True)
    health_parser = subparsers.add_parser("daily-health")
    health_parser.add_argument("--at", type=_datetime_argument)
    health_parser.add_argument("--hours", type=int, default=24)
    health_parser.add_argument("--json", action="store_true")
    health_parser.add_argument("--verbose", action="store_true")
    add_switchbot_parser(subparsers)
    arguments = parser.parse_args(argv)

    if arguments.command == "switchbot":
        return run_switchbot(arguments)

    if arguments.command == "daily-health":
        checked_at = arguments.at or datetime.now(timezone.utc)
        connection = None
        try:
            database_path = Configuration.database_path_from_environment()
            device_dns = Configuration.device_dns_from_environment()
            storage = Storage(database_path)
            connection = storage.connect_readonly()
            report = DailyHealthService(
                storage, database_path, device_dns
            ).check(checked_at, arguments.hours)
        except Exception as error:
            report = {
                "status": "critical",
                "checked_at": checked_at.isoformat(),
                "window_start": None,
                "window_end": checked_at.isoformat(),
                "warnings": [],
                "critical": [
                    {
                        "source": "daily-health",
                        "subject": None,
                        "problem": f"execution failed: {type(error).__name__}",
                        "latest_timestamp": None,
                        "expected": "successful read-only check",
                        "actual": "unavailable",
                    }
                ],
                "source_summaries": {},
                "backup_summary": {},
                "database_summary": {},
            }
        finally:
            if connection is not None:
                connection.close()
        if arguments.json:
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        else:
            _print_daily_health(report, arguments.verbose)
        if report["status"] == "critical":
            return 2
        return 1 if report["status"] == "warning" else 0

    if arguments.command == "backup":
        destination = _backup()
        print(f"Backup created: {destination}")
        return

    if arguments.command == "import-fusionsolar-reports":
        database_path = Configuration.database_path_from_environment()
        storage = Storage(database_path)
        connection = storage.connect()
        try:
            importer = FusionSolarReportImporter(storage)
            report = (
                importer.inspect(arguments.path)
                if arguments.inspect
                else importer.run(arguments.path, dry_run=arguments.dry_run)
            )
        finally:
            connection.close()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report["status"] == "blocked" else 0

    if arguments.command == "import-fusionsolar-gas-queue":
        if arguments.inspect:
            report = FusionSolarGasQueueImporter().inspect(arguments.path)
        else:
            storage = Storage(Configuration.database_path_from_environment())
            connection = (
                storage.connect_readonly() if arguments.dry_run else storage.connect()
            )
            try:
                report = FusionSolarGasQueueImporter(storage).run(
                    arguments.path, dry_run=arguments.dry_run
                )
            finally:
                connection.close()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report["status"] == "blocked" else 0

    argument_start = getattr(arguments, "start", None)
    argument_end = getattr(arguments, "end", None)
    if (argument_start is None) != (argument_end is None):
        parser.error("--start and --end must be specified together")
    if argument_start is not None and argument_start > argument_end:
        parser.error("--start must not be after --end")

    if arguments.command == "quality":
        report = _quality(arguments.start, arguments.end)
        summary = report["summary"]
        assert isinstance(summary, dict)
        issue_counts = {
            "Duplicate records": report["duplicate_records"],
            "Invalid values": report["invalid_values"],
            "Unexpected metrics": len(report["unexpected_metrics"]),
            "Unexpected units": report["unexpected_units"],
            "Missing metric points": len(report["missing_metric_points"]),
            "Irregular intervals": len(report["irregular_intervals"]),
        }
        print(f"Records: {summary['record_count']}")
        print(f"Timestamps: {summary['timestamp_count']}")
        for label, count in issue_counts.items():
            print(f"{label}: {count}")
        issues_found = any(issue_counts.values())
        print("Quality issues found." if issues_found else "Quality check passed.")
        return 1 if issues_found else 0

    if arguments.command == "quality-diagnose":
        diagnosis = _quality_diagnose(arguments.start, arguments.end)
        _print_quality_diagnosis(diagnosis)
        return 0

    if arguments.command == "collect-device-realtime":
        device_dns = (
            [arguments.device_dn]
            if arguments.device_dn
            else Configuration.device_dns_from_environment()
        )
        application, connection = _create_device_realtime_application()
        try:
            raw_data_list, failures = application.run_device_realtime(device_dns)
        finally:
            connection.close()
        print(
            f"Collected {len(raw_data_list)} device-realtime RawData item(s). "
            f"Failed {len(failures)}."
        )
        return 1 if failures and not raw_data_list else 0

    if arguments.command == "collect-realtime":
        device_dns = Configuration.device_dns_from_environment()
        battery_device_dn, battery_sigids = (
            Configuration.battery_dc_from_environment()
        )
        application, connection = _create_realtime_application()
        try:
            report = application.run_realtime_snapshot(
                device_dns, battery_device_dn, battery_sigids
            )
        finally:
            connection.close()
        failed_parts = [key for key in report if key.endswith("_error")]
        for name in ("device", "battery", "alarm"):
            value = report.get(name)
            if isinstance(value, tuple):
                collected, failures = value
                print(
                    f"{name}: collected {len(collected)}, "
                    f"failed {len(failures)}"
                )
                if failures and not collected:
                    failed_parts.append(name)
        return 1 if failed_parts else 0

    if arguments.command == "collect-battery-dc":
        if arguments.device_dn and arguments.sigids:
            device_dn, sigids = arguments.device_dn, arguments.sigids
        elif arguments.device_dn or arguments.sigids:
            parser.error("--device-dn and --sigids must be specified together")
        else:
            device_dn, sigids = Configuration.battery_dc_from_environment()
        module_ids = arguments.module_id or [1, 2, 3, 4]
        application, connection = _create_battery_dc_application()
        try:
            raw_data_list, failures = application.run_battery_dc(
                device_dn, sigids, module_ids
            )
        finally:
            connection.close()
        print(
            f"Collected {len(raw_data_list)} battery-dc RawData item(s). "
            f"Failed {len(failures)}."
        )
        return 1 if failures and not raw_data_list else 0

    if arguments.command in {
        "collect-alarms-current",
        "collect-alarms-history",
    }:
        device_dns = (
            [arguments.device_dn]
            if arguments.device_dn
            else Configuration.device_dns_from_environment()
        )
        application, connection = _create_alarm_application()
        try:
            if arguments.command == "collect-alarms-current":
                raw_data_list, failures = application.run_current_alarms(
                    device_dns
                )
                label = "current alarm"
            else:
                raw_data_list, failures = application.run_alarm_history(
                    device_dns, arguments.start, arguments.end
                )
                label = "alarm-history"
        finally:
            connection.close()
        print(
            f"Collected {len(raw_data_list)} {label} RawData item(s). "
            f"Failed {len(failures)}."
        )
        return 1 if failures and not raw_data_list else 0

    if arguments.command == "build-energy-balance-records":
        application, connection = _create_energy_balance_application()
        try:
            record_count = application.build_energy_balance_records(
                arguments.start, arguments.end
            )
        finally:
            connection.close()
        print(f"Built {record_count} energy-balance Record item(s).")
        return 0

    if arguments.command == "quality-energy-balance":
        application, connection = _create_energy_balance_application()
        try:
            report = application.check_energy_balance_quality(
                arguments.start, arguments.end
            )
        finally:
            connection.close()
        print(f"RawData: {report['raw_data_count']}")
        print(f"Quality issues: {len(report['issues'])}")
        print(f"RawData without Records: {len(report['raw_data_without_records'])}")
        return 1 if report["issues"] or report["raw_data_without_records"] else 0

    if arguments.command == "backfill-energy-balance":
        application, connection = _create_energy_balance_application()
        try:
            raw_data_list = application.backfill_missing_energy_balance(
                arguments.start, arguments.end
            )
        finally:
            connection.close()
        print(
            f"Backfilled {len(raw_data_list)} energy-balance RawData item(s) "
            "and rebuilt Records."
        )
        return 0

    if arguments.command == "diagnose-device-realtime":
        configuration = Configuration.from_environment()
        storage = Storage(configuration.database_path)
        connection = storage.connect()
        try:
            report = Application(None, storage, None).diagnose_device_realtime()
        finally:
            connection.close()
        print(f"Collections: {report['collection_count']}")
        for device_dn, count in report["by_device"].items():
            print(f"{device_dn}: {count}")
        return 0

    if arguments.command in {
        "quality-battery-dc",
        "diagnose-battery-dc",
        "quality-alarms",
        "diagnose-alarms",
    }:
        configuration = Configuration.from_environment()
        storage = Storage(configuration.database_path)
        connection = storage.connect()
        try:
            application = Application(None, storage, None)
            if arguments.command == "quality-battery-dc":
                report = application.check_battery_dc_quality()
            elif arguments.command == "diagnose-battery-dc":
                report = application.diagnose_battery_dc()
            elif arguments.command == "quality-alarms":
                report = application.check_alarm_quality(
                    Configuration.device_dns_from_environment()
                )
            else:
                report = application.diagnose_alarms()
        finally:
            connection.close()
        print(f"Collections: {report['collection_count']}")
        print(f"Invalid responses: {report['invalid_responses']}")
        if "by_module" in report:
            print("By module:")
            _print_counts(report["by_module"])
            print("Empty responses by module:")
            _print_counts(report["empty_responses_by_module"])
            print("Signal ID changes by module:")
            _print_counts(report["signal_id_changes_by_module"])
        if "by_source" in report:
            print("By source:")
            _print_counts(report["by_source"])
            print("By device:")
            _print_counts(report["by_device"])
            print("History by date:")
            _print_counts(report["history_by_date"])
            print("Current gaps by device:")
            _print_counts(report["current_gaps_by_device"])
            print(f"Pagination issues: {report['pagination_issues']}")
        if "total_hits" in report:
            print(f"Alarm hits: {report['total_hits']}")
        if "issue_count" in report:
            print(f"Quality issues: {report['issue_count']}")
            return 1 if report["issue_count"] else 0
        return 0

    if arguments.command == "collect-energy-balance":
        application, connection = _create_energy_balance_application()
        try:
            if arguments.start is None:
                today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
                raw_data_list = [
                    application.run_energy_balance_for_date(today)
                ]
            else:
                raw_data_list = application.run_energy_balance_range(
                    arguments.start, arguments.end
                )
        finally:
            connection.close()
        print(
            f"Collected {len(raw_data_list)} energy-balance RawData item(s)."
        )
        return

    if arguments.command == "collect":
        if arguments.start is None:
            main()
            print("Collected 1 RawData item.")
            return
        application, connection = _create_application()
        try:
            raw_data_list = application.run_range(
                arguments.start, arguments.end
            )
        finally:
            connection.close()
        print(f"Collected {len(raw_data_list)} RawData items.")
        return

    application, connection = _create_application()
    try:
        if arguments.command == "missing":
            missing_dates = application.find_missing_dates(
                arguments.start, arguments.end
            )
        else:
            raw_data_list = application.backfill_missing(
                arguments.start, arguments.end
            )
    finally:
        connection.close()

    if arguments.command == "missing":
        if not missing_dates:
            print("No missing dates.")
        for missing_date in missing_dates:
            print(missing_date.isoformat())
        print(f"Missing {len(missing_dates)} date(s).")
    else:
        print(f"Backfilled {len(raw_data_list)} RawData item(s).")


if __name__ == "__main__":
    cli()
