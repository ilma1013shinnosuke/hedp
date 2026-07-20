import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from hedp.raw_data import RawData
from hedp.record import Record


class Storage:
    _SNAPSHOT_SOURCES = {
        "fusionsolar_device_realtime",
        "fusionsolar_battery_dc",
        "fusionsolar_alarm_current",
    }
    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        self._connection: Optional[sqlite3.Connection] = None

    def connect(self) -> sqlite3.Connection:
        self._connection = sqlite3.connect(self.database_path)
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
            f"{database.as_uri()}?mode=ro", uri=True
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
        return [
            item
            for item in self.load_rawdata()
            if start <= item.timestamp <= end
        ]

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
        backup_connection = sqlite3.connect(destination)
        try:
            connection.backup(backup_connection)
        finally:
            backup_connection.close()

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
