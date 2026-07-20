import sqlite3
from typing import Optional

from hedp.raw_data import RawData


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
        self._connection.commit()
        return self._connection

    def save_rawdata(self, raw_data: RawData) -> None:
        connection = self._require_connection()
        connection.execute(
            "INSERT INTO raw_data (data) VALUES (?)",
            (raw_data.to_json(),),
        )
        connection.commit()

    def load_rawdata(self) -> list[RawData]:
        connection = self._require_connection()
        rows = connection.execute(
            "SELECT data FROM raw_data ORDER BY id"
        ).fetchall()
        return [RawData.from_json(row[0]) for row in rows]

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("Storage is not connected")
        return self._connection
