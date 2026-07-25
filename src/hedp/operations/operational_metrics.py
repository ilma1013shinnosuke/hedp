"""Small, anonymous metrics for observing SumiCore operations.

The module deliberately accepts only a fixed vocabulary.  It never returns a
database path, device identifier, payload, exception text, wall-clock time, or
secret.  Database inspection uses SQLite's read-only mode and an immediate
timeout so the probe never waits on, or writes to, the production database.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import shutil
import sqlite3
from time import monotonic


class OperationName(str, Enum):
    COLLECTION = "collection"
    BACKUP = "backup"
    HEALTH_CHECK = "health_check"
    DATABASE_PROBE = "database_probe"


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
            "operation": self.operation.value,
            "outcome": self.outcome.value,
            "duration": self.duration,
            "failure_category": self.failure_category.value,
        }


@dataclass(frozen=True)
class DatabaseCapacityMetric:
    """Anonymous capacity and non-blocking SQLite read-only probe metadata."""

    status: str
    database_bytes: int
    filesystem_free_bytes: int
    page_count: int | None
    free_page_count: int | None
    raw_data_rows: int | None
    record_rows: int | None
    probe_duration: str

    def to_dict(self) -> dict[str, int | str | None]:
        return {
            "status": self.status,
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

    def collect(self, database_path: str | Path) -> DatabaseCapacityMetric:
        database = Path(database_path).resolve()
        started = monotonic()
        try:
            usage = shutil.disk_usage(database.parent)
            database_bytes = database.stat().st_size
        except OSError:
            return DatabaseCapacityMetric(
                status="unavailable",
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
                status=status,
                database_bytes=database_bytes,
                filesystem_free_bytes=usage.free,
                page_count=None,
                free_page_count=None,
                raw_data_rows=None,
                record_rows=None,
                probe_duration=duration_bucket(monotonic() - started),
            )

        return DatabaseCapacityMetric(
            status="ok",
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
