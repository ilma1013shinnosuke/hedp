import argparse
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from hedp.application import Application
from hedp.configuration import Configuration
from hedp.fusionsolar_client import FusionSolarClient
from hedp.fusionsolar_collector import FusionSolarCollector
from hedp.fusionsolar_record_builder import FusionSolarRecordBuilder
from hedp.raw_data import RawData
from hedp.storage import Storage


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
        application = Application(None, storage, None)  # type: ignore[arg-type]
        return application.check_quality(start_date, end_date)
    finally:
        connection.close()


def _quality_diagnose(start_date: date, end_date: date) -> dict[str, object]:
    configuration = Configuration.from_environment()
    storage = Storage(configuration.database_path)
    connection = storage.connect()
    try:
        application = Application(None, storage, None)  # type: ignore[arg-type]
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


def cli(argv: Optional[list[str]] = None) -> Optional[int]:
    parser = argparse.ArgumentParser(prog="hedp")
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect_parser = subparsers.add_parser("collect")
    collect_parser.add_argument("--start", type=_date_argument)
    collect_parser.add_argument("--end", type=_date_argument)
    missing_parser = subparsers.add_parser("missing")
    missing_parser.add_argument("--start", type=_date_argument, required=True)
    missing_parser.add_argument("--end", type=_date_argument, required=True)
    backfill_parser = subparsers.add_parser("backfill-missing")
    backfill_parser.add_argument("--start", type=_date_argument, required=True)
    backfill_parser.add_argument("--end", type=_date_argument, required=True)
    subparsers.add_parser("backup")
    quality_parser = subparsers.add_parser("quality")
    quality_parser.add_argument("--start", type=_date_argument, required=True)
    quality_parser.add_argument("--end", type=_date_argument, required=True)
    diagnose_parser = subparsers.add_parser("quality-diagnose")
    diagnose_parser.add_argument("--start", type=_date_argument, required=True)
    diagnose_parser.add_argument("--end", type=_date_argument, required=True)
    arguments = parser.parse_args(argv)

    if arguments.command == "backup":
        destination = _backup()
        print(f"Backup created: {destination}")
        return

    if (arguments.start is None) != (arguments.end is None):
        parser.error("--start and --end must be specified together")
    if arguments.start is not None and arguments.start > arguments.end:
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
