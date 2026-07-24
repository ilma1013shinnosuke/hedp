#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from hedp.adapters.switchbot.storage import SwitchBotStorage
from hedp.storage import Storage
from hedp.storage.jsonl_archive import (
    ArchiveValidationError,
    load_archive_manifest,
    verify_archive_matches_records,
)


PRESERVED_TABLES = (
    "raw_data",
    "records",
    "switchbot_schema",
    "switchbot_devices",
    "switchbot_device_names",
    "switchbot_device_locations",
    "switchbot_collection_events",
    "switchbot_import_runs",
    "switchbot_import_conflicts",
    "switchbot_data_gaps",
    "switchbot_hourly_summary",
)


def _quote_identifier(value: str) -> str:
    if value not in {*PRESERVED_TABLES, "switchbot_observations"}:
        raise ValueError("unexpected database identifier")
    return f'"{value}"'


def _create_empty_database(path: Path) -> None:
    common = Storage(str(path))
    connection = common.connect()
    connection.close()
    switchbot = SwitchBotStorage(str(path))
    switchbot.connect()
    switchbot.close()


def _columns(
    connection: sqlite3.Connection,
    database: str,
    table: str,
) -> list[str]:
    if database not in {"main", "source_database"}:
        raise ValueError("unexpected database name")
    quoted = _quote_identifier(table)
    return [
        str(row[1])
        for row in connection.execute(f"PRAGMA {database}.table_info({quoted})")
    ]


def _validate_schema(connection: sqlite3.Connection) -> None:
    expected = {*PRESERVED_TABLES, "switchbot_observations"}
    source_tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM source_database.sqlite_schema "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    unknown = sorted(source_tables - expected)
    missing = sorted(expected - source_tables)
    if unknown or missing:
        raise ArchiveValidationError(
            "source database table set does not match the compact builder"
        )
    for table in expected:
        if _columns(connection, "main", table) != _columns(
            connection, "source_database", table
        ):
            raise ArchiveValidationError(f"{table} schema mismatch")


def _copy_table(connection: sqlite3.Connection, table: str) -> None:
    quoted = _quote_identifier(table)
    columns = _columns(connection, "main", table)
    column_list = ",".join(f'"{column}"' for column in columns)
    connection.execute(f"DELETE FROM main.{quoted}")
    connection.execute(
        f"INSERT INTO main.{quoted} ({column_list}) "
        f"SELECT {column_list} FROM source_database.{quoted}"
    )


def _archive_selection(manifest: dict[str, Any]) -> tuple[str, str, str]:
    if manifest.get("schema_name") != "switchbot_observations":
        raise ArchiveValidationError("archive has an unexpected schema")
    source = manifest.get("source")
    selection = manifest.get("selection")
    if not isinstance(source, str) or not isinstance(selection, dict):
        raise ArchiveValidationError("archive selection is unavailable")
    start = selection.get("start")
    end = selection.get("end_exclusive")
    if not isinstance(start, str) or not isinstance(end, str) or start >= end:
        raise ArchiveValidationError("archive selection range is invalid")
    return source, start, end


def _archived_rows(
    connection: sqlite3.Connection,
    *,
    source: str,
    start: str,
    end: str,
) -> Iterator[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT *
        FROM source_database.switchbot_observations
        WHERE source=?
          AND observed_at_utc>=?
          AND observed_at_utc<?
        ORDER BY observation_id
        """,
        (source, start, end),
    )
    for row in rows:
        yield dict(row)


def _validated_archives(
    connection: sqlite3.Connection,
    archives: list[Path],
) -> list[tuple[str, str, str, int]]:
    ranges: list[tuple[str, str, str, int]] = []
    for archive in archives:
        manifest = load_archive_manifest(archive)
        source, start, end = _archive_selection(manifest)
        verify_archive_matches_records(
            archive,
            _archived_rows(
                connection,
                source=source,
                start=start,
                end=end,
            ),
        )
        ranges.append((source, start, end, int(manifest["record_count"])))
    ranges.sort()
    for previous, current in zip(ranges, ranges[1:]):
        if previous[0] == current[0] and previous[2] > current[1]:
            raise ArchiveValidationError("archive selection ranges overlap")
    return ranges


def _copy_observations(
    connection: sqlite3.Connection,
    ranges: list[tuple[str, str, str, int]],
) -> None:
    columns = _columns(connection, "main", "switchbot_observations")
    column_list = ",".join(f'"{column}"' for column in columns)
    parameters: list[str] = []
    exclusions = []
    for source, start, end, _ in ranges:
        exclusions.append(
            "(source=? AND observed_at_utc>=? AND observed_at_utc<?)"
        )
        parameters.extend((source, start, end))
    where = " OR ".join(exclusions)
    connection.execute("DELETE FROM main.switchbot_observations")
    connection.execute(
        f"INSERT INTO main.switchbot_observations ({column_list}) "
        f"SELECT {column_list} "
        "FROM source_database.switchbot_observations "
        f"WHERE NOT ({where})",
        parameters,
    )


def _count(
    connection: sqlite3.Connection,
    database: str,
    table: str,
) -> int:
    quoted = _quote_identifier(table)
    return int(
        connection.execute(
            f"SELECT count(*) FROM {database}.{quoted}"
        ).fetchone()[0]
    )


def build_compact_database(
    source_database: str | Path,
    destination: str | Path,
    archives: list[str | Path],
) -> dict[str, Any]:
    source = Path(source_database).resolve()
    final = Path(destination)
    archive_paths = [Path(path) for path in archives]
    if final.exists():
        raise FileExistsError(final)
    if not archive_paths:
        raise ValueError("at least one verified archive is required")
    final.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{final.name}.",
        suffix=".partial",
        dir=final.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    os.chmod(temporary, 0o600)
    connection: sqlite3.Connection | None = None
    try:
        _create_empty_database(temporary)
        connection = sqlite3.connect(temporary, timeout=30, uri=True)
        connection.row_factory = sqlite3.Row
        source_uri = f"{source.as_uri()}?mode=ro"
        connection.execute("ATTACH DATABASE ? AS source_database", (source_uri,))
        connection.execute("BEGIN")
        _validate_schema(connection)
        ranges = _validated_archives(connection, archive_paths)
        for table in PRESERVED_TABLES:
            _copy_table(connection, table)
        _copy_observations(connection, ranges)

        archived_count = sum(item[3] for item in ranges)
        source_observations = _count(
            connection, "source_database", "switchbot_observations"
        )
        compact_observations = _count(
            connection, "main", "switchbot_observations"
        )
        if compact_observations + archived_count != source_observations:
            raise ArchiveValidationError("observation count reconciliation failed")
        for table in PRESERVED_TABLES:
            if _count(connection, "main", table) != _count(
                connection, "source_database", table
            ):
                raise ArchiveValidationError(f"{table} count mismatch")
        connection.commit()
        connection.execute("DETACH DATABASE source_database")
        checks = [
            row[0] for row in connection.execute("PRAGMA integrity_check")
        ]
        if checks != ["ok"]:
            raise ArchiveValidationError("compact database integrity check failed")
        connection.close()
        connection = None
        os.chmod(temporary, 0o600)
        os.replace(temporary, final)
        return {
            "source_size_bytes": source.stat().st_size,
            "compact_size_bytes": final.stat().st_size,
            "source_observations": source_observations,
            "compact_observations": compact_observations,
            "archived_observations": archived_count,
            "archive_count": len(ranges),
            "integrity": "ok",
        }
    finally:
        if connection is not None:
            connection.close()
        temporary.unlink(missing_ok=True)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description=(
            "Build a separate compact DB after proving monthly archives "
            "exactly match the source"
        )
    )
    value.add_argument("--database", required=True)
    value.add_argument("--output", required=True)
    value.add_argument("--archive", action="append", required=True)
    return value


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    report = build_compact_database(
        arguments.database,
        arguments.output,
        arguments.archive,
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
