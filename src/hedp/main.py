import argparse
import sqlite3
from datetime import date
from typing import Optional

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


def cli(argv: Optional[list[str]] = None) -> None:
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
    arguments = parser.parse_args(argv)

    if (arguments.start is None) != (arguments.end is None):
        parser.error("--start and --end must be specified together")
    if arguments.start is not None and arguments.start > arguments.end:
        parser.error("--start must not be after --end")

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
