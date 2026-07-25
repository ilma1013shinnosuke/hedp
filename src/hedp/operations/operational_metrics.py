"""Small, anonymous metrics for observing SumiCore operations.

The module deliberately accepts only a fixed vocabulary.  It never returns a
database path, device identifier, payload, exception text, wall-clock time, or
secret.  Database inspection uses SQLite's read-only mode and an immediate
timeout so the probe never waits on, or writes to, the production database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
from time import monotonic
from typing import Protocol


class OperationName(str, Enum):
    """Fixed job names used by the supported scheduled runners."""

    DEVICE_REALTIME = "device_realtime"
    SWITCHBOT = "switchbot"
    EQUIPMENT = "equipment"
    DAILY_HEALTH = "daily_health"
    DAILY = "daily"


class OperationOutcome(str, Enum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"
    FAILED = "failed"


class FailureCategory(str, Enum):
    NONE = "none"
    LOCK_HELD = "lock_held"
    TIMEOUT = "timeout"
    NETWORK = "network"
    INVALID_RESPONSE = "invalid_response"
    CONFIGURATION = "configuration"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


class MetricKind(str, Enum):
    OPERATION = "operation"
    DATABASE = "database"


class DatabaseProbeStatus(str, Enum):
    OK = "ok"
    LOCKED = "locked"
    UNAVAILABLE = "unavailable"


class MetricPayload(Protocol):
    """Safe metric values that can be added to the append-only journal."""

    def to_dict(self) -> dict[str, int | str | None]: ...


def duration_bucket(elapsed_seconds: float) -> str:
    """Return a coarse duration category, never the exact elapsed value."""
    if elapsed_seconds < 0:
        raise ValueError("elapsed_seconds must not be negative")
    if elapsed_seconds < 1:
        return "under_1s"
    if elapsed_seconds < 5:
        return "1_to_5s"
    if elapsed_seconds < 30:
        return "5_to_30s"
    return "30s_or_more"


@dataclass(frozen=True)
class OperationMetric:
    """A safe result summary for a single operation attempt."""

    operation: OperationName
    outcome: OperationOutcome
    duration: str
    failure_category: FailureCategory

    @classmethod
    def from_result(
        cls,
        operation: OperationName,
        outcome: OperationOutcome,
        elapsed_seconds: float,
        failure_category: FailureCategory = FailureCategory.NONE,
    ) -> "OperationMetric":
        if outcome is OperationOutcome.COMPLETED and failure_category is not FailureCategory.NONE:
            raise ValueError("completed operations cannot have a failure category")
        if outcome is not OperationOutcome.COMPLETED and failure_category is FailureCategory.NONE:
            raise ValueError("non-completed operations require a failure category")
        if outcome is OperationOutcome.TIMED_OUT and failure_category is not FailureCategory.TIMEOUT:
            raise ValueError("timed_out operations require the timeout category")
        return cls(operation, outcome, duration_bucket(elapsed_seconds), failure_category)

    def to_dict(self) -> dict[str, str]:
        return {
            "job": self.operation.value,
            "outcome": self.outcome.value,
            "duration": self.duration,
            "failure_category": self.failure_category.value,
        }


@dataclass(frozen=True)
class DatabaseCapacityMetric:
    """Anonymous capacity and non-blocking SQLite read-only probe metadata."""

    job: OperationName
    status: DatabaseProbeStatus
    database_bytes: int
    filesystem_free_bytes: int
    page_count: int | None
    free_page_count: int | None
    raw_data_rows: int | None
    record_rows: int | None
    probe_duration: str

    def to_dict(self) -> dict[str, int | str | None]:
        return {
            "job": self.job.value,
            "status": self.status.value,
            "database_bytes": self.database_bytes,
            "filesystem_free_bytes": self.filesystem_free_bytes,
            "page_count": self.page_count,
            "free_page_count": self.free_page_count,
            "raw_data_rows": self.raw_data_rows,
            "record_rows": self.record_rows,
            "probe_duration": self.probe_duration,
        }


class ReadOnlyDatabaseMetrics:
    """Collect metadata without reading table payloads or writing the database."""

    def collect(
        self,
        database_path: str | Path,
        *,
        job: OperationName = OperationName.DAILY_HEALTH,
    ) -> DatabaseCapacityMetric:
        database = Path(database_path).resolve()
        started = monotonic()
        try:
            usage = shutil.disk_usage(database.parent)
            database_bytes = database.stat().st_size
        except OSError:
            return DatabaseCapacityMetric(
                job=job,
                status=DatabaseProbeStatus.UNAVAILABLE,
                database_bytes=0,
                filesystem_free_bytes=0,
                page_count=None,
                free_page_count=None,
                raw_data_rows=None,
                record_rows=None,
                probe_duration=duration_bucket(monotonic() - started),
            )

        try:
            connection = sqlite3.connect(
                f"{database.as_uri()}?mode=ro", uri=True, timeout=0
            )
            try:
                connection.execute("PRAGMA query_only = ON")
                page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
                free_page_count = int(
                    connection.execute("PRAGMA freelist_count").fetchone()[0]
                )
                raw_data_rows = self._count_if_present(connection, "raw_data")
                record_rows = self._count_if_present(connection, "records")
            finally:
                connection.close()
        except sqlite3.OperationalError as error:
            status = "locked" if "locked" in str(error).lower() else "unavailable"
            return DatabaseCapacityMetric(
                job=job,
                status=(
                    DatabaseProbeStatus.LOCKED
                    if status == "locked"
                    else DatabaseProbeStatus.UNAVAILABLE
                ),
                database_bytes=database_bytes,
                filesystem_free_bytes=usage.free,
                page_count=None,
                free_page_count=None,
                raw_data_rows=None,
                record_rows=None,
                probe_duration=duration_bucket(monotonic() - started),
            )

        return DatabaseCapacityMetric(
            job=job,
            status=DatabaseProbeStatus.OK,
            database_bytes=database_bytes,
            filesystem_free_bytes=usage.free,
            page_count=page_count,
            free_page_count=free_page_count,
            raw_data_rows=raw_data_rows,
            record_rows=record_rows,
            probe_duration=duration_bucket(monotonic() - started),
        )

    @staticmethod
    def _count_if_present(connection: sqlite3.Connection, table: str) -> int | None:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not exists:
            return None
        return int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


class OperationalMetricsJournal:
    """Append anonymised, date-only records to a private local JSONL journal.

    The journal is intentionally independent of the database and repository.
    It retains an active file plus two rotated generations, has no payload field,
    and accepts only the typed fixed-vocabulary metric objects above.
    """

    filename = "operational-metrics.jsonl"
    maximum_bytes = 1024 * 1024
    generations = 2

    def __init__(self, state_home: str | Path | None = None) -> None:
        configured_path = os.environ.get("SUMICORE_OPERATIONAL_METRICS_PATH")
        if configured_path:
            self._custom_path = True
            self._path = self._absolute_path(configured_path)
            self._directory = self._path.parent
            self._state_home = self._directory.parent
        else:
            self._custom_path = False
            if state_home is None:
                state_home = os.environ.get("XDG_STATE_HOME")
            self._state_home = self._absolute_path(
                state_home or Path.home() / ".local" / "state"
            )
            self._directory = self._state_home / "sumicore"
            self._path = self._directory / self.filename

    @staticmethod
    def _absolute_path(value: str | Path) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError("operational metrics path must be absolute")
        return path

    @property
    def path(self) -> Path:
        """Return the configured journal location for local maintenance only."""
        return self._path

    def append(self, metric: OperationMetric | DatabaseCapacityMetric) -> None:
        """Write one date-only, schema-controlled JSONL record."""
        record = {
            "date": datetime.now(timezone.utc).date().isoformat(),
            "kind": (
                MetricKind.OPERATION.value
                if isinstance(metric, OperationMetric)
                else MetricKind.DATABASE.value
            ),
            **metric.to_dict(),
        }
        encoded = (json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n").encode(
            "utf-8"
        )
        self._prepare_directory()
        self._rotate_if_needed(len(encoded))
        self._append_bytes(encoded)

    def _prepare_directory(self) -> None:
        self._ensure_safe_state_home()
        if self._custom_path:
            self._ensure_custom_private_directory(self._directory)
        else:
            self._ensure_private_directory(self._directory)

    def _ensure_safe_state_home(self) -> None:
        if self._state_home.exists() or self._state_home.is_symlink():
            metadata = os.lstat(self._state_home)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise RuntimeError("operational metrics directory is unsafe")
            return
        self._state_home.mkdir(mode=0o700, parents=True, exist_ok=False)
        metadata = os.lstat(self._state_home)
        if not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeError("operational metrics directory is unsafe")

    @staticmethod
    def _ensure_private_directory(directory: Path) -> None:
        if directory.exists() or directory.is_symlink():
            metadata = os.lstat(directory)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise RuntimeError("operational metrics directory is unsafe")
        else:
            directory.mkdir(mode=0o700, parents=True, exist_ok=False)
            metadata = os.lstat(directory)
            if not stat.S_ISDIR(metadata.st_mode):
                raise RuntimeError("operational metrics directory is unsafe")
        os.chmod(directory, 0o700)

    @staticmethod
    def _ensure_custom_private_directory(directory: Path) -> None:
        if directory.exists() or directory.is_symlink():
            metadata = os.lstat(directory)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise RuntimeError("operational metrics directory is unsafe")
            if stat.S_IMODE(metadata.st_mode) != 0o700:
                raise RuntimeError("operational metrics directory must be private")
            return
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        metadata = os.lstat(directory)
        if not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeError("operational metrics directory is unsafe")
        os.chmod(directory, 0o700)

    def _rotate_if_needed(self, incoming_size: int) -> None:
        if not self._path.exists() and not self._path.is_symlink():
            return
        metadata = os.lstat(self._path)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("operational metrics file is unsafe")
        if metadata.st_size + incoming_size <= self.maximum_bytes:
            return
        oldest = self._generation_path(self.generations)
        self._remove_regular_file_if_present(oldest)
        for generation in range(self.generations - 1, 0, -1):
            source = self._generation_path(generation)
            if source.exists() or source.is_symlink():
                self._require_regular_file(source)
                os.replace(source, self._generation_path(generation + 1))
        os.replace(self._path, self._generation_path(1))

    def _append_bytes(self, encoded: bytes) -> None:
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        if self._path.exists() or self._path.is_symlink():
            self._require_regular_file(self._path)
            descriptor = os.open(self._path, os.O_WRONLY | os.O_APPEND | no_follow)
        else:
            descriptor = os.open(
                self._path,
                os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_EXCL | no_follow,
                0o600,
            )
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, encoded)
        finally:
            os.close(descriptor)

    def _generation_path(self, generation: int) -> Path:
        return self._path.with_name(f"{self._path.name}.{generation}")

    @staticmethod
    def _require_regular_file(path: Path) -> None:
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("operational metrics file is unsafe")

    def _remove_regular_file_if_present(self, path: Path) -> None:
        if not path.exists() and not path.is_symlink():
            return
        self._require_regular_file(path)
        path.unlink()
