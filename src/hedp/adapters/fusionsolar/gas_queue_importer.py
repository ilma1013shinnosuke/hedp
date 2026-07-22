from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from hedp.adapters.fusionsolar.energy_balance_record_builder import (
    FusionSolarEnergyBalanceRecordBuilder,
)
from hedp.storage import RawData, Storage


SCHEMA_VERSION = 2
MAX_FILE_BYTES = 24 * 1024 * 1024
MAX_PAYLOAD_BYTES = 10 * 1024 * 1024
MAX_FILES = 100
FILENAME = re.compile(
    r"^(fusionsolar(?:_energy_balance)?)_(\d{4}-\d{2}-\d{2})_([0-9a-f]{16})\.json$"
)
TOKYO = ZoneInfo("Asia/Tokyo")


class GasQueueError(ValueError):
    pass


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GasQueueError("duplicate_json_key")
        result[key] = value
    return result


def _constant(_: str) -> None:
    raise GasQueueError("non_finite_number")


def _loads(value: str) -> Any:
    return json.loads(value, object_pairs_hook=_pairs, parse_constant=_constant)


@dataclass(frozen=True)
class Candidate:
    file_name: str
    source: str
    target_date: date
    collected_at: datetime
    payload_sha256: str
    envelope_sha256: str
    payload: dict[str, Any]

    def raw_data(self) -> RawData:
        return RawData(
            source=self.source,
            timestamp=self.collected_at,
            target_date=self.target_date,
            payload=self.payload,
            metadata={
                "transport": "gas_drive_queue",
                "schema_version": SCHEMA_VERSION,
                "source_file": self.file_name,
                "payload_sha256": self.payload_sha256,
            },
        )


class FusionSolarGasQueueImporter:
    """Validate a downloaded GAS queue and atomically preserve its RawData."""

    def __init__(self, storage: Storage | None = None) -> None:
        self.storage = storage

    def inspect(self, path: Path) -> dict[str, Any]:
        candidates = self._candidates(path)
        return self._report("inspected", candidates, 0, 0)

    def run(self, path: Path, *, dry_run: bool = False) -> dict[str, Any]:
        if self.storage is None:
            raise GasQueueError("storage_required")
        candidates = self._candidates(path)
        connection = self.storage._require_connection()
        duplicates, conflicts = self._compare(connection, candidates)
        if conflicts:
            return self._report("blocked", candidates, duplicates, conflicts)
        if dry_run:
            return self._report("dry_run", candidates, duplicates, 0)

        connection.execute("BEGIN IMMEDIATE")
        try:
            self._create_receipts(connection)
            duplicates, conflicts = self._compare(connection, candidates)
            if conflicts:
                connection.rollback()
                return self._report("blocked", candidates, duplicates, conflicts)
            for candidate in candidates:
                if self._receipt_exists(connection, candidate):
                    continue
                cursor = connection.execute(
                    "INSERT INTO raw_data (data) VALUES (?)",
                    (candidate.raw_data().to_json(),),
                )
                connection.execute(
                    """INSERT INTO gas_import_receipts
                    (schema_version, source, target_date, payload_sha256,
                     file_name, envelope_sha256, collected_at, imported_at,
                     raw_data_id, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'imported')""",
                    (
                        SCHEMA_VERSION, candidate.source,
                        candidate.target_date.isoformat(),
                        candidate.payload_sha256, candidate.file_name,
                        candidate.envelope_sha256,
                        candidate.collected_at.isoformat(),
                        datetime.now(timezone.utc).isoformat(), cursor.lastrowid,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        return self._report("completed", candidates, duplicates, 0)

    def _candidates(self, path: Path) -> list[Candidate]:
        if path.is_symlink():
            raise GasQueueError("symlink_not_allowed")
        files = sorted(path.iterdir()) if path.is_dir() else [path]
        files = [item for item in files if item.name.endswith(".json")]
        if not files:
            raise GasQueueError("no_json_files")
        if len(files) > MAX_FILES:
            raise GasQueueError("too_many_files")
        candidates = [self._read(item) for item in files]
        identities: dict[tuple[str, date], str] = {}
        for item in candidates:
            key = (item.source, item.target_date)
            previous = identities.setdefault(key, item.payload_sha256)
            if previous != item.payload_sha256:
                raise GasQueueError("same_day_payload_conflict")
        return candidates

    def _read(self, path: Path) -> Candidate:
        match = FILENAME.fullmatch(path.name)
        if not match:
            raise GasQueueError("invalid_filename")
        if path.parent.is_symlink() or path.is_symlink():
            raise GasQueueError("symlink_not_allowed")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            before = os.fstat(descriptor)
            if before.st_size > MAX_FILE_BYTES:
                raise GasQueueError("file_too_large")
            chunks = []
            remaining = MAX_FILE_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            after = os.fstat(descriptor)
            if len(content) > MAX_FILE_BYTES:
                raise GasQueueError("file_too_large")
            if (before.st_ino, before.st_size) != (after.st_ino, after.st_size):
                raise GasQueueError("file_changed_during_read")
        finally:
            os.close(descriptor)
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise GasQueueError("invalid_utf8") from error
        envelope = _loads(text)
        if not isinstance(envelope, dict):
            raise GasQueueError("envelope_not_object")
        expected = {
            "schema_version", "source", "collected_at", "target_date",
            "request", "payload_sha256", "payload_text",
        }
        if set(envelope) != expected or envelope.get("schema_version") != SCHEMA_VERSION:
            raise GasQueueError("invalid_envelope_schema")
        source, day_text, prefix = match.groups()
        if envelope["source"] != source or envelope["target_date"] != day_text:
            raise GasQueueError("filename_metadata_mismatch")
        target = date.fromisoformat(day_text)
        payload_text = envelope["payload_text"]
        if not isinstance(payload_text, str):
            raise GasQueueError("payload_text_not_string")
        payload_bytes = payload_text.encode("utf-8")
        if len(payload_bytes) > MAX_PAYLOAD_BYTES:
            raise GasQueueError("payload_too_large")
        digest = hashlib.sha256(payload_bytes).hexdigest()
        if envelope["payload_sha256"] != digest or prefix != digest[:16]:
            raise GasQueueError("payload_hash_mismatch")
        payload = _loads(payload_text)
        if not isinstance(payload, dict):
            raise GasQueueError("payload_not_object")
        collected = self._utc_timestamp(envelope["collected_at"])
        self._validate_request(source, envelope["request"])
        self._reject_secrets(envelope["request"])
        self._reject_secrets(payload)
        candidate = Candidate(
            path.name, source, target, collected, digest,
            hashlib.sha256(content).hexdigest(), payload,
        )
        self._validate_payload(candidate)
        return candidate

    @staticmethod
    def _utc_timestamp(value: Any) -> datetime:
        if not isinstance(value, str) or not value.endswith("Z"):
            raise GasQueueError("collected_at_not_utc")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise GasQueueError("invalid_collected_at") from error
        if parsed.utcoffset() != timedelta(0):
            raise GasQueueError("collected_at_not_utc")
        if parsed > datetime.now(timezone.utc) + timedelta(minutes=10):
            raise GasQueueError("collected_at_in_future")
        return parsed

    @staticmethod
    def _validate_request(source: str, request: Any) -> None:
        allowed = {
            "fusionsolar": ("POST", "/rest/pvms/web/report/v1/station/station-kpi-list", "statDim", "2"),
            "fusionsolar_energy_balance": ("GET", "/rest/pvms/web/station/v1/overview/energy-balance", "timeDim", "2"),
        }
        if not isinstance(request, dict):
            raise GasQueueError("invalid_request")
        method, endpoint, key, value = allowed[source]
        if request.get("method") != method or request.get("endpoint") != endpoint:
            raise GasQueueError("request_not_allowed")
        if request.get(key) != value:
            raise GasQueueError("request_dimension_not_allowed")

    @classmethod
    def _reject_secrets(cls, value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if any(word in key.lower() for word in ("authorization", "cookie", "password", "secret", "token")):
                    raise GasQueueError("sensitive_field_present")
                cls._reject_secrets(nested)
        elif isinstance(value, list):
            for nested in value:
                cls._reject_secrets(nested)

    @staticmethod
    def _validate_payload(item: Candidate) -> None:
        raw = item.raw_data()
        if item.source == "fusionsolar_energy_balance":
            FusionSolarEnergyBalanceRecordBuilder().build(raw)
            return
        data = item.payload.get("data")
        rows = data.get("list") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise GasQueueError("station_rows_missing")
        metrics = {"productPower", "inverterPower", "onGridPower", "buyPower", "powerProfit"}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("fmtCollectTimeStr"), str):
                raise GasQueueError("invalid_station_row")
            try:
                timestamp = datetime.fromisoformat(row["fmtCollectTimeStr"]).replace(tzinfo=TOKYO)
            except ValueError as error:
                raise GasQueueError("invalid_station_timestamp") from error
            if timestamp.date() != item.target_date:
                raise GasQueueError("station_date_mismatch")
            for key in metrics & row.keys():
                value = row[key]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise GasQueueError("invalid_station_metric")

    @staticmethod
    def _create_receipts(connection: Any) -> None:
        connection.execute("""CREATE TABLE IF NOT EXISTS gas_import_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schema_version INTEGER NOT NULL, source TEXT NOT NULL,
            target_date TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
            file_name TEXT NOT NULL, envelope_sha256 TEXT NOT NULL,
            collected_at TEXT NOT NULL, imported_at TEXT NOT NULL,
            raw_data_id INTEGER, status TEXT NOT NULL,
            UNIQUE(schema_version, source, target_date, payload_sha256)
        )""")

    @staticmethod
    def _receipt_exists(connection: Any, item: Candidate) -> bool:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='gas_import_receipts'"
        ).fetchone()
        if not table:
            return False
        row = connection.execute(
            """SELECT envelope_sha256, file_name FROM gas_import_receipts
            WHERE schema_version=? AND source=? AND target_date=? AND payload_sha256=?""",
            (SCHEMA_VERSION, item.source, item.target_date.isoformat(), item.payload_sha256),
        ).fetchone()
        if row and row != (item.envelope_sha256, item.file_name):
            raise GasQueueError("receipt_metadata_conflict")
        return bool(row)

    def _compare(self, connection: Any, items: list[Candidate]) -> tuple[int, int]:
        duplicates = conflicts = 0
        for item in items:
            if self._receipt_exists(connection, item):
                duplicates += 1
                continue
            rows = connection.execute(
                "SELECT data FROM raw_data WHERE json_extract(data, '$.source')=? AND json_extract(data, '$.target_date')=?",
                (item.source, item.target_date.isoformat()),
            ).fetchall()
            if any(RawData.from_json(row[0]).payload == item.payload for row in rows):
                duplicates += 1
            elif rows:
                conflicts += 1
        return duplicates, conflicts

    @staticmethod
    def _report(status: str, items: list[Candidate], duplicates: int, conflicts: int) -> dict[str, Any]:
        return {
            "status": status, "files_checked": len(items),
            "ready_to_import": len(items) - duplicates - conflicts,
            "duplicates_skipped": duplicates, "conflicts": conflicts,
            "files": [
                {"file": item.file_name, "source": item.source,
                 "target_date": item.target_date.isoformat(),
                 "payload_sha256": item.payload_sha256}
                for item in items
            ],
        }
