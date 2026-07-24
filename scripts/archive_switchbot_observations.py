#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from hedp.storage.jsonl_archive import create_jsonl_gzip_archive


def month_bounds(month: str) -> tuple[str, str]:
    try:
        start = datetime.strptime(month, "%Y-%m")
    except ValueError as error:
        raise ValueError("month must use YYYY-MM") from error
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return (
        start.strftime("%Y-%m-%dT00:00:00+00:00"),
        end.strftime("%Y-%m-%dT00:00:00+00:00"),
    )


def connect_readonly(database_path: str | Path) -> sqlite3.Connection:
    path = Path(database_path).resolve()
    connection = sqlite3.connect(
        f"{path.as_uri()}?mode=ro",
        uri=True,
        timeout=30,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def inspect_month(
    connection: sqlite3.Connection,
    *,
    month: str,
    source: str,
) -> dict[str, Any]:
    start, end = month_bounds(month)
    row = connection.execute(
        """
        SELECT count(*) AS record_count,
               min(observed_at_utc) AS first_timestamp,
               max(observed_at_utc) AS last_timestamp,
               coalesce(sum(length(raw_payload_json)), 0) AS raw_payload_bytes
        FROM switchbot_observations
        WHERE source=?
          AND observed_at_utc>=?
          AND observed_at_utc<?
        """,
        (source, start, end),
    ).fetchone()
    assert row is not None
    return {
        "month": month,
        "source": source,
        "record_count": row["record_count"],
        "first_timestamp": row["first_timestamp"],
        "last_timestamp": row["last_timestamp"],
        "raw_payload_bytes": row["raw_payload_bytes"],
    }


def iter_month(
    connection: sqlite3.Connection,
    *,
    month: str,
    source: str,
) -> Iterator[dict[str, Any]]:
    start, end = month_bounds(month)
    rows = connection.execute(
        """
        SELECT *
        FROM switchbot_observations
        WHERE source=?
          AND observed_at_utc>=?
          AND observed_at_utc<?
        ORDER BY observation_id
        """,
        (source, start, end),
    )
    for row in rows:
        yield dict(row)


def database_schema_version(connection: sqlite3.Connection) -> str:
    row = connection.execute(
        "SELECT max(version) FROM switchbot_schema"
    ).fetchone()
    if row is None or row[0] is None:
        raise RuntimeError("SwitchBot schema version is unavailable")
    return str(row[0])


def create_month_archive(
    database_path: str | Path,
    destination: str | Path,
    *,
    month: str,
    source: str = "switchbot_csv_export",
) -> dict[str, Any]:
    connection = connect_readonly(database_path)
    try:
        inspection = inspect_month(connection, month=month, source=source)
        if inspection["record_count"] == 0:
            raise ValueError("the selected month has no observations")
        schema_version = database_schema_version(connection)
        return create_jsonl_gzip_archive(
            iter_month(connection, month=month, source=source),
            destination,
            source=source,
            schema_name="switchbot_observations",
        schema_version=schema_version,
        timestamp_field="observed_at_utc",
        created_by="sumicore archive-switchbot-observations",
        selection={
            "month": month,
            "start": month_bounds(month)[0],
            "end_exclusive": month_bounds(month)[1],
        },
    )
    finally:
        connection.close()


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description=(
            "Inspect or create a read-only monthly SwitchBot observation archive"
        )
    )
    value.add_argument("--database", required=True)
    value.add_argument("--month", required=True)
    value.add_argument("--source", default="switchbot_csv_export")
    value.add_argument("--output")
    value.add_argument("--inspect", action="store_true")
    return value


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    if arguments.inspect:
        connection = connect_readonly(arguments.database)
        try:
            report = inspect_month(
                connection,
                month=arguments.month,
                source=arguments.source,
            )
        finally:
            connection.close()
    else:
        if not arguments.output:
            parser().error("--output is required unless --inspect is used")
        manifest = create_month_archive(
            arguments.database,
            arguments.output,
            month=arguments.month,
            source=arguments.source,
        )
        report = {
            "month": arguments.month,
            "source": arguments.source,
            "record_count": manifest["record_count"],
            "compressed_size_bytes": manifest["compressed_size_bytes"],
            "archive_name": Path(arguments.output).name,
            "verified": True,
        }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
