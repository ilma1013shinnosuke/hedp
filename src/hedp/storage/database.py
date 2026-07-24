import errno
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from .raw_data import RawData
from .record import Record


class Storage:
    _SNAPSHOT_SOURCES = {
        "fusionsolar_device_realtime",
        "fusionsolar_battery_dc",
        "fusionsolar_alarm_current",
        "fusionsolar_modbus_tcp",
    }
    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        self._connection: Optional[sqlite3.Connection] = None

    def connect(self) -> sqlite3.Connection:
        self._connection = sqlite3.connect(self.database_path, timeout=30)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data TEXT NOT NULL
            )
            """
        )
        self._connection.commit()
        return self._connection

    def connect_readonly(self) -> sqlite3.Connection:
        database = Path(self.database_path).resolve()
        self._connection = sqlite3.connect(
            f"{database.as_uri()}?mode=ro", uri=True, timeout=30
        )
        return self._connection

    def save_rawdata(self, raw_data: RawData) -> None:
        connection = self._require_connection()
        data = raw_data.to_json()
        payload = json.dumps(raw_data.payload)
        metadata = (
            json.dumps(raw_data.metadata)
            if raw_data.metadata is not None
            else None
        )
        target_date = (
            raw_data.target_date.isoformat()
            if raw_data.target_date is not None
            else None
        )
        if raw_data.source in self._SNAPSHOT_SOURCES:
            connection.execute(
                """
                INSERT INTO raw_data (data)
                SELECT ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM raw_data
                    WHERE json_extract(data, '$.source') = ?
                      AND json_extract(data, '$.timestamp') = ?
                      AND json(json_extract(data, '$.metadata')) = json(?)
                      AND json(json_extract(data, '$.payload')) = json(?)
                )
                """,
                (
                    data,
                    raw_data.source,
                    raw_data.timestamp.isoformat(),
                    json.dumps(raw_data.metadata),
                    payload,
                ),
            )
            connection.commit()
            return
        connection.execute(
            """
            INSERT INTO raw_data (data)
            SELECT ?
            WHERE NOT EXISTS (
                SELECT 1
                FROM raw_data
                WHERE json_extract(data, '$.source') = ?
                  AND (
                      (? IS NULL AND json_extract(data, '$.target_date') IS NULL)
                      OR json_extract(data, '$.target_date') = ?
                  )
                  AND json(json_extract(data, '$.payload')) = json(?)
                  AND (
                      (? IS NULL AND json_extract(data, '$.metadata') IS NULL)
                      OR json(json_extract(data, '$.metadata')) = json(?)
                  )
            )
            """,
            (
                data,
                raw_data.source,
                target_date,
                target_date,
                payload,
                metadata,
                metadata,
            ),
        )
        connection.commit()

    def load_rawdata_for_range(
        self, source: str, start_date: date, end_date: date
    ) -> list[RawData]:
        connection = self._require_connection()
        rows = connection.execute(
            """
            SELECT data FROM raw_data
            WHERE json_extract(data, '$.source') = ?
              AND json_extract(data, '$.target_date') BETWEEN ? AND ?
            ORDER BY json_extract(data, '$.target_date'), id
            """,
            (source, start_date.isoformat(), end_date.isoformat()),
        ).fetchall()
        return [RawData.from_json(row[0]) for row in rows]

    def load_rawdata(self) -> list[RawData]:
        connection = self._require_connection()
        rows = connection.execute(
            "SELECT data FROM raw_data ORDER BY id"
        ).fetchall()
        return [RawData.from_json(row[0]) for row in rows]

    def load_rawdata_in_window(
        self, start: datetime, end: datetime
    ) -> list[RawData]:
        connection = self._require_connection()
        rows = connection.execute(
            """
            SELECT data FROM raw_data
            WHERE json_extract(data, '$.timestamp') BETWEEN ? AND ?
            ORDER BY id
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [RawData.from_json(row[0]) for row in rows]

    def load_rawdata_for_sources(
        self, sources: tuple[str, ...] | list[str] | set[str]
    ) -> list[RawData]:
        connection = self._require_connection()
        ordered = tuple(sorted(set(sources)))
        if not ordered:
            return []
        placeholders = ",".join("?" for _ in ordered)
        rows = connection.execute(
            f"""
            SELECT data FROM raw_data
            WHERE json_extract(data, '$.source') IN ({placeholders})
            ORDER BY id
            """,
            ordered,
        ).fetchall()
        return [RawData.from_json(row[0]) for row in rows]

    def count_rawdata(self) -> int:
        connection = self._require_connection()
        return int(connection.execute("SELECT count(*) FROM raw_data").fetchone()[0])

    def count_records(self) -> int:
        connection = self._require_connection()
        return int(connection.execute("SELECT count(*) FROM records").fetchone()[0])

    def integrity_check(self) -> list[str]:
        connection = self._require_connection()
        return [row[0] for row in connection.execute("PRAGMA integrity_check")]

    def save_records(self, records: list[Record]) -> None:
        connection = self._require_connection()
        connection.executemany(
            """
            INSERT INTO records (data)
            SELECT ?
            WHERE NOT EXISTS (
                SELECT 1 FROM records WHERE data = ?
            )
            """,
            [(data, data) for data in (record.to_json() for record in records)],
        )
        connection.commit()

    def load_records(self) -> list[Record]:
        connection = self._require_connection()
        rows = connection.execute(
            "SELECT data FROM records ORDER BY id"
        ).fetchall()
        return [Record.from_json(row[0]) for row in rows]

    def load_records_for_source_timestamp(
        self, source: str, timestamp: datetime
    ) -> list[Record]:
        connection = self._require_connection()
        rows = connection.execute(
            """
            SELECT data FROM records
            WHERE json_extract(data, '$.source') = ?
              AND json_extract(data, '$.timestamp') = ?
            ORDER BY id
            """,
            (source, timestamp.isoformat()),
        ).fetchall()
        return [Record.from_json(row[0]) for row in rows]

    def load_records_for_source_window(
        self, source: str, start: datetime, end: datetime
    ) -> list[Record]:
        connection = self._require_connection()
        rows = connection.execute(
            """
            SELECT data FROM records
            WHERE json_extract(data, '$.source') = ?
              AND json_extract(data, '$.timestamp') BETWEEN ? AND ?
            ORDER BY id
            """,
            (source, start.isoformat(), end.isoformat()),
        ).fetchall()
        return [Record.from_json(row[0]) for row in rows]

    def load_records_for_range(
        self,
        source: str,
        start_date: date,
        end_date: date,
        timezone_name: str = "Asia/Tokyo",
    ) -> list[Record]:
        timezone = ZoneInfo(timezone_name)
        connection = self._require_connection()
        rows = connection.execute(
            """
            SELECT data
            FROM records
            WHERE json_extract(data, '$.source') = ?
            """,
            (source,),
        ).fetchall()
        records = [
            record
            for row in rows
            for record in (Record.from_json(row[0]),)
            if start_date
            <= record.timestamp.astimezone(timezone).date()
            <= end_date
        ]
        return sorted(records, key=lambda record: (record.timestamp, record.metric))

    def backup(self, destination_path: str) -> None:
        connection = self._require_connection()
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source_size = Path(self.database_path).resolve().stat().st_size
        reserve_size = max(512 * 1024 * 1024, source_size // 5)
        required_size = source_size + reserve_size
        available_size = shutil.disk_usage(destination.parent).free
        if available_size < required_size:
            raise OSError(
                errno.ENOSPC,
                "insufficient free space for an atomic database backup "
                f"(required={required_size}, available={available_size})",
            )

        file_descriptor, partial_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".partial",
            dir=destination.parent,
        )
        os.close(file_descriptor)
        partial = Path(partial_name)
        backup_connection: Optional[sqlite3.Connection] = None
        try:
            backup_connection = sqlite3.connect(partial)
            connection.backup(backup_connection)
            backup_connection.close()
            backup_connection = None
            os.replace(partial, destination)
        finally:
            if backup_connection is not None:
                backup_connection.close()
            for unfinished_path in (
                partial,
                Path(f"{partial}-journal"),
                Path(f"{partial}-wal"),
                Path(f"{partial}-shm"),
            ):
                unfinished_path.unlink(missing_ok=True)

    def get_record_dates(
        self,
        source: str,
        start_date: date,
        end_date: date,
        timezone_name: str = "Asia/Tokyo",
    ) -> set[date]:
        timezone = ZoneInfo(timezone_name)
        return {
            record.timestamp.astimezone(timezone).date()
            for record in self.load_records()
            if record.source == source
            and start_date
            <= record.timestamp.astimezone(timezone).date()
            <= end_date
        }

    def get_collected_dates(
        self,
        source: str,
        start_date: date,
        end_date: date,
    ) -> set[date]:
        return {
            raw_data.target_date
            for raw_data in self.load_rawdata()
            if raw_data.source == source
            and raw_data.target_date is not None
            and start_date <= raw_data.target_date <= end_date
        }

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("Storage is not connected")
        return self._connection
