import json
import sqlite3
from typing import Optional

from hedp.raw_data import RawData
from hedp.record import Record


class Storage:
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

    def save_rawdata(self, raw_data: RawData) -> None:
        connection = self._require_connection()
        data = raw_data.to_json()
        payload = json.dumps(raw_data.payload)
        connection.execute(
            """
            INSERT INTO raw_data (data)
            SELECT ?
            WHERE NOT EXISTS (
                SELECT 1
                FROM raw_data
                WHERE json_extract(data, '$.source') = ?
                  AND json(json_extract(data, '$.payload')) = json(?)
            )
            """,
            (data, raw_data.source, payload),
        )
        connection.commit()

    def load_rawdata(self) -> list[RawData]:
        connection = self._require_connection()
        rows = connection.execute(
            "SELECT data FROM raw_data ORDER BY id"
        ).fetchall()
        return [RawData.from_json(row[0]) for row in rows]

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

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("Storage is not connected")
        return self._connection
