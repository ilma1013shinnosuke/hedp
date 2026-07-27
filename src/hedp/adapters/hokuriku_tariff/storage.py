"""Append-only SQLite storage used only by offline/test tariff ingestion."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from .models import TariffDataset


class OfflineTariffRepository:
    """A deliberately isolated repository; it cannot open the production DB."""

    REQUIRED_SUFFIX = ".tariff-test.sqlite3"

    def __init__(self, database_path: str | Path) -> None:
        path = Path(database_path).expanduser().resolve()
        if not path.name.endswith(self.REQUIRED_SUFFIX):
            raise ValueError(f"offline tariff DB must end with {self.REQUIRED_SUFFIX}")
        self.path = path
        self.connection: sqlite3.Connection | None = None

    def open(self) -> "OfflineTariffRepository":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self._migrate()
        return self

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def __enter__(self) -> "OfflineTariffRepository":
        return self.open()

    def __exit__(self, *_: object) -> None:
        self.close()

    def ingest(self, dataset: TariffDataset, *, recorded_at: datetime) -> int:
        connection = self._require_connection()
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise ValueError("recorded_at must include a UTC offset")
        connection.execute(
            """
            INSERT OR IGNORE INTO hokuriku_tariff_raw
                (sha256, source_url, fetched_at, content_type, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                dataset.raw.sha256,
                dataset.raw.source_url,
                dataset.raw.fetched_at.isoformat(),
                dataset.raw.content_type,
                dataset.raw.payload,
            ),
        )
        count = 0
        for entity_type, entities in (
            ("document", dataset.documents),
            ("plan", dataset.plans),
            ("rate", dataset.rates),
        ):
            for entity in entities:
                payload_json = _canonical_json(entity)
                entity_key = _entity_key(entity_type, entity)
                revision_id = hashlib.sha256(
                    f"{entity_type}\0{entity_key}\0{payload_json}".encode()
                ).hexdigest()
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO hokuriku_tariff_history
                        (revision_id, entity_type, entity_key, payload_json,
                         effective_from, effective_until, status, quality,
                         source_id, raw_sha256, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        revision_id,
                        entity_type,
                        entity_key,
                        payload_json,
                        _iso_or_none(getattr(entity, "effective_from", None)),
                        _iso_or_none(getattr(entity, "effective_until", None)),
                        getattr(entity, "status").value,
                        getattr(entity, "quality").value,
                        getattr(entity, "source_id"),
                        dataset.raw.sha256,
                        recorded_at.isoformat(),
                    ),
                )
                count += cursor.rowcount
        connection.commit()
        return count

    def raw_payload(self, sha256: str) -> bytes | None:
        row = self._require_connection().execute(
            "SELECT payload FROM hokuriku_tariff_raw WHERE sha256 = ?",
            (sha256,),
        ).fetchone()
        return None if row is None else bytes(row["payload"])

    def history(self, entity_type: str, entity_key: str) -> list[dict[str, Any]]:
        rows = self._require_connection().execute(
            """
            SELECT payload_json FROM hokuriku_tariff_history
            WHERE entity_type = ? AND entity_key = ?
            ORDER BY recorded_at, rowid
            """,
            (entity_type, entity_key),
        )
        return [json.loads(row["payload_json"]) for row in rows]

    def current(
        self,
        entity_type: str,
        *,
        as_of: date,
    ) -> dict[str, dict[str, Any]]:
        rows = self._require_connection().execute(
            """
            SELECT entity_key, payload_json, status, effective_from, effective_until,
                   recorded_at, rowid
            FROM hokuriku_tariff_history
            WHERE entity_type = ?
              AND (effective_from IS NULL OR effective_from <= ?)
              AND (effective_until IS NULL OR effective_until >= ?)
            ORDER BY entity_key, COALESCE(effective_from, ''), recorded_at, rowid
            """,
            (entity_type, as_of.isoformat(), as_of.isoformat()),
        )
        latest: dict[str, sqlite3.Row] = {}
        for row in rows:
            latest[row["entity_key"]] = row
        return {
            key: json.loads(row["payload_json"])
            for key, row in latest.items()
            if row["status"] != "cancelled"
        }

    def future(
        self,
        entity_type: str,
        *,
        after: date,
    ) -> list[dict[str, Any]]:
        rows = self._require_connection().execute(
            """
            SELECT payload_json FROM hokuriku_tariff_history
            WHERE entity_type = ? AND effective_from > ?
            ORDER BY effective_from, recorded_at, rowid
            """,
            (entity_type, after.isoformat()),
        )
        return [json.loads(row["payload_json"]) for row in rows]

    def latest_fetch_at(self) -> datetime | None:
        row = self._require_connection().execute(
            "SELECT MAX(fetched_at) AS fetched_at FROM hokuriku_tariff_raw"
        ).fetchone()
        if row is None or row["fetched_at"] is None:
            return None
        return datetime.fromisoformat(row["fetched_at"])

    def _migrate(self) -> None:
        self._require_connection().executescript(
            """
            CREATE TABLE IF NOT EXISTS hokuriku_tariff_schema (
                version INTEGER NOT NULL
            );
            INSERT INTO hokuriku_tariff_schema(version)
            SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM hokuriku_tariff_schema);

            CREATE TABLE IF NOT EXISTS hokuriku_tariff_raw (
                sha256 TEXT PRIMARY KEY,
                source_url TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                content_type TEXT NOT NULL,
                payload BLOB NOT NULL
            );

            CREATE TABLE IF NOT EXISTS hokuriku_tariff_history (
                revision_id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_key TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                effective_from TEXT,
                effective_until TEXT,
                status TEXT NOT NULL,
                quality TEXT NOT NULL,
                source_id TEXT NOT NULL,
                raw_sha256 TEXT NOT NULL REFERENCES hokuriku_tariff_raw(sha256),
                recorded_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_hokuriku_tariff_history_lookup
                ON hokuriku_tariff_history(entity_type, entity_key, effective_from);
            """
        )
        self._require_connection().commit()

    def _require_connection(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("offline tariff repository is not open")
        return self.connection


def _entity_key(entity_type: str, entity: object) -> str:
    if entity_type == "document":
        return str(getattr(entity, "source_id"))
    return str(getattr(entity, "entity_key"))


def _canonical_json(value: object) -> str:
    if not is_dataclass(value):
        raise TypeError("tariff history entities must be dataclasses")
    return json.dumps(
        asdict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _iso_or_none(value: date | None) -> str | None:
    return None if value is None else value.isoformat()
