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
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
from time import monotonic, sleep, time
from typing import Iterator, Protocol


class OperationName(str, Enum):
    """Fixed job names used by the supported scheduled runners."""

    DEVICE_REALTIME = "device_realtime"
    MODBUS_REALTIME = "modbus_realtime"
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
    OPERATOR = "operator"


class DatabaseProbeStatus(str, Enum):
    OK = "ok"
    LOCKED = "locked"
    UNAVAILABLE = "unavailable"


class OperatorActivity(str, Enum):
    """Human effort categories without free-form household context."""

    WARNING_REVIEW = "warning_review"
    MANUAL_RECOVERY = "manual_recovery"


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
class OperatorMetric:
    """Coarse human effort and counts for release-operability review."""

    activity: OperatorActivity
    count: int
    duration: str

    @classmethod
    def from_observation(
        cls,
        activity: OperatorActivity,
        count: int,
        elapsed_seconds: float,
    ) -> "OperatorMetric":
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 1000:
            raise ValueError("operator metric count must be between 1 and 1000")
        return cls(activity, count, duration_bucket(elapsed_seconds))

    def to_dict(self) -> dict[str, int | str]:
        return {
            "activity": self.activity.value,
            "count": self.count,
            "duration": self.duration,
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
        include_table_counts: bool = False,
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
                # Exact row counts can scan multi-gigabyte tables.  They are
                # therefore opt-in diagnostics, never part of the daily probe.
                raw_data_rows = (
                    self._count_if_present(connection, "raw_data")
                    if include_table_counts
                    else None
                )
                record_rows = (
                    self._count_if_present(connection, "records")
                    if include_table_counts
                    else None
                )
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
    # The journal is written by several launchd jobs.  Keep contention short:
    # a missed diagnostic is preferable to delaying the job that it describes.
    lock_wait_seconds = 0.5
    lock_retry_seconds = 0.01
    # A stale lock is recovered only after its owner is known to be gone.  The
    # deliberately generous age avoids stealing a lock from a slow filesystem.
    stale_lock_seconds = 60.0
    _lock_owner_filename = "owner.json"

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

    def append(
        self,
        metric: OperationMetric | DatabaseCapacityMetric | OperatorMetric,
    ) -> None:
        """Write one date-only, schema-controlled JSONL record."""
        record = {
            "date": datetime.now(timezone.utc).date().isoformat(),
            "kind": (
                MetricKind.OPERATION.value
                if isinstance(metric, OperationMetric)
                else MetricKind.OPERATOR.value
                if isinstance(metric, OperatorMetric)
                else MetricKind.DATABASE.value
            ),
            **metric.to_dict(),
        }
        encoded = (json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n").encode(
            "utf-8"
        )
        self._prepare_directory()
        with self._exclusive_lock():
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
        try:
            self._state_home.mkdir(mode=0o700, parents=True, exist_ok=False)
        except FileExistsError:
            # Another scheduled job won the creation race.  Validate the
            # object it created rather than treating a harmless race as a
            # metrics failure.
            metadata = os.lstat(self._state_home)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise RuntimeError("operational metrics directory is unsafe") from None
            return
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
            try:
                directory.mkdir(mode=0o700, parents=True, exist_ok=False)
            except FileExistsError:
                metadata = os.lstat(directory)
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                    raise RuntimeError("operational metrics directory is unsafe") from None
            else:
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
        try:
            directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        except FileExistsError:
            metadata = os.lstat(directory)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise RuntimeError("operational metrics directory is unsafe") from None
            if stat.S_IMODE(metadata.st_mode) != 0o700:
                raise RuntimeError("operational metrics directory must be private")
            return
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

    @property
    def _lock_path(self) -> Path:
        return self._path.with_name(f".{self._path.name}.lock")

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        """Serialise append and rotation with a portable private mkdir lock.

        Advisory file locks differ across platforms and can be released when a
        descriptor is accidentally inherited.  Creating a directory is atomic
        on the supported local filesystems, so it also protects the rename
        sequence used for rotation.  Lock metadata contains only an OS process
        id and a coarse creation timestamp; it is never added to the journal.
        """
        deadline = monotonic() + self.lock_wait_seconds
        acquired = False
        while not acquired:
            try:
                self._lock_path.mkdir(mode=0o700)
                self._write_lock_owner()
                acquired = True
            except FileExistsError:
                self._recover_stale_lock_if_safe()
                if monotonic() >= deadline:
                    raise RuntimeError("operational metrics journal is busy")
                sleep(self.lock_retry_seconds)
            except OSError as error:
                raise RuntimeError("operational metrics journal lock failed") from error
        try:
            yield
        finally:
            self._release_lock()

    def _write_lock_owner(self) -> None:
        owner_path = self._lock_path / self._lock_owner_filename
        descriptor = os.open(
            owner_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            os.write(
                descriptor,
                json.dumps({"pid": os.getpid(), "created_at": int(time())}).encode(
                    "utf-8"
                ),
            )
        except Exception:
            os.close(descriptor)
            self._release_lock()
            raise
        else:
            os.close(descriptor)

    def _recover_stale_lock_if_safe(self) -> None:
        """Detach a dead, old lock without following or deleting unknown files."""
        lock_path = self._lock_path
        try:
            metadata = os.lstat(lock_path)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeError("operational metrics journal lock is unsafe")
        if time() - metadata.st_mtime < self.stale_lock_seconds:
            return
        owner = self._read_lock_owner(lock_path / self._lock_owner_filename)
        if owner is None:
            # A process can die after mkdir and before owner metadata is
            # written.  Recover only an empty old directory; a malformed or
            # unexpected lock is left untouched for a human to inspect.
            try:
                if any(lock_path.iterdir()):
                    return
            except OSError:
                return
        elif self._owner_process_is_alive(owner):
            return

        # Renaming first is atomic: a new writer may safely acquire the now
        # vacant lock path while this process disposes of the detached one.
        detached = lock_path.with_name(
            f".{self._path.name}.stale-{os.getpid()}-{int(monotonic() * 1_000_000)}"
        )
        try:
            os.rename(lock_path, detached)
        except FileNotFoundError:
            return
        except OSError:
            return
        self._remove_own_detached_lock(detached)

    @staticmethod
    def _read_lock_owner(owner_path: Path) -> int | None:
        try:
            metadata = os.lstat(owner_path)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                return None
            owner = json.loads(owner_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        pid = owner.get("pid") if isinstance(owner, dict) else None
        return pid if type(pid) is int and pid > 0 else None

    @staticmethod
    def _owner_process_is_alive(pid: int) -> bool:
        if pid == os.getpid():
            return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except (PermissionError, OSError):
            # An inaccessible or platform-specific process is not proof that it
            # is dead, so leave the lock alone.
            return True
        return True

    def _remove_own_detached_lock(self, detached: Path) -> None:
        """Clean only the exact private lock structure created by this class."""
        try:
            contents = list(detached.iterdir())
            if not contents:
                detached.rmdir()
                return
            if len(contents) != 1 or contents[0].name != self._lock_owner_filename:
                return
            metadata = os.lstat(contents[0])
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                return
            contents[0].unlink()
            detached.rmdir()
        except OSError:
            # Detached remnants do not affect future journal writes.
            return

    def _release_lock(self) -> None:
        try:
            owner_path = self._lock_path / self._lock_owner_filename
            if owner_path.exists() and not owner_path.is_symlink():
                self._require_regular_file(owner_path)
                owner_path.unlink()
            self._lock_path.rmdir()
        except (FileNotFoundError, OSError, RuntimeError):
            # Metrics must never make their caller fail while releasing a lock.
            return

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


def summarize_operational_metrics(
    state_home: str | Path | None = None,
) -> dict[str, object]:
    """Return aggregate facts from the private journal and two old generations.

    This reader is deliberately stricter than the writer: records must have the
    exact, published schema and vocabulary before they affect a report.  Broken
    lines are counted but never returned, so an accidental payload in a journal
    cannot be surfaced by a status command.
    """
    journal = OperationalMetricsJournal(state_home)
    paths = [
        journal._generation_path(generation)
        for generation in range(journal.generations, 0, -1)
    ] + [journal.path]
    records: list[dict[str, object]] = []
    invalid_lines = 0
    files_read = 0
    for path in paths:
        if not path.exists() and not path.is_symlink():
            continue
        try:
            journal._require_regular_file(path)
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError, RuntimeError):
            invalid_lines += 1
            continue
        files_read += 1
        for line in text.splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                invalid_lines += 1
                continue
            if not _is_valid_metric_record(record):
                invalid_lines += 1
                continue
            records.append(record)

    operation_counts: dict[tuple[str, str, str, str, str], int] = {}
    operator_counts: dict[tuple[str, str, str], int] = {}
    database_by_date: dict[str, int] = {}
    for record in records:
        if record["kind"] == MetricKind.OPERATION.value:
            key = tuple(
                str(record[field])
                for field in ("date", "job", "outcome", "failure_category", "duration")
            )
            operation_counts[key] = operation_counts.get(key, 0) + 1
        elif record["kind"] == MetricKind.OPERATOR.value:
            key = tuple(
                str(record[field]) for field in ("date", "activity", "duration")
            )
            operator_counts[key] = operator_counts.get(key, 0) + int(record["count"])
        elif record["status"] == DatabaseProbeStatus.OK.value:
            # Later valid entries for one date replace earlier ones.  Exact time
            # is not stored, so this is only a daily observation, not an event log.
            database_by_date[str(record["date"])] = int(record["database_bytes"])

    database_dates = sorted(database_by_date)
    first_bytes = database_by_date[database_dates[0]] if database_dates else None
    last_bytes = database_by_date[database_dates[-1]] if database_dates else None
    return {
        "schema_version": 1,
        "files_read": files_read,
        "accepted_records": len(records),
        "invalid_lines": invalid_lines,
        "operation_counts": [
            {
                "date": key[0],
                "job": key[1],
                "outcome": key[2],
                "failure_category": key[3],
                "duration": key[4],
                "count": count,
            }
            for key, count in sorted(operation_counts.items())
        ],
        "operator_counts": [
            {
                "date": key[0],
                "activity": key[1],
                "duration": key[2],
                "count": count,
            }
            for key, count in sorted(operator_counts.items())
        ],
        "database_capacity": {
            "observed_days": len(database_dates),
            "first_database_bytes": first_bytes,
            "last_database_bytes": last_bytes,
            "database_bytes_delta": (
                last_bytes - first_bytes
                if first_bytes is not None and last_bytes is not None
                else None
            ),
        },
    }


def _is_valid_metric_record(record: object) -> bool:
    if not isinstance(record, dict) or not isinstance(record.get("date"), str):
        return False
    try:
        parsed_date = datetime.strptime(record["date"], "%Y-%m-%d")
    except ValueError:
        return False
    if parsed_date.strftime("%Y-%m-%d") != record["date"]:
        return False
    if record.get("kind") == MetricKind.OPERATION.value:
        return (
            set(record)
            == {"date", "kind", "job", "outcome", "duration", "failure_category"}
            and record["job"] in {item.value for item in OperationName}
            and record["outcome"] in {item.value for item in OperationOutcome}
            and record["duration"]
            in {"under_1s", "1_to_5s", "5_to_30s", "30s_or_more"}
            and record["failure_category"] in {item.value for item in FailureCategory}
        )
    if record.get("kind") == MetricKind.DATABASE.value:
        expected = {
            "date", "kind", "job", "status", "database_bytes", "filesystem_free_bytes",
            "page_count", "free_page_count", "raw_data_rows", "record_rows", "probe_duration",
        }
        numeric = ("database_bytes", "filesystem_free_bytes")
        optional_numeric = ("page_count", "free_page_count", "raw_data_rows", "record_rows")
        return (
            set(record) == expected
            and record["job"] in {item.value for item in OperationName}
            and record["status"] in {item.value for item in DatabaseProbeStatus}
            and record["probe_duration"]
            in {"under_1s", "1_to_5s", "5_to_30s", "30s_or_more"}
            and all(type(record[field]) is int and record[field] >= 0 for field in numeric)
            and all(
                record[field] is None
                or (type(record[field]) is int and record[field] >= 0)
                for field in optional_numeric
            )
        )
    if record.get("kind") == MetricKind.OPERATOR.value:
        return (
            set(record) == {"date", "kind", "activity", "count", "duration"}
            and record["activity"] in {item.value for item in OperatorActivity}
            and type(record["count"]) is int
            and 1 <= record["count"] <= 1000
            and record["duration"]
            in {"under_1s", "1_to_5s", "5_to_30s", "30s_or_more"}
        )
    return False
