"""Finite read-only qualification runs backed only by a dedicated test DB.

The harness owns no device transport.  A caller injects a bounded read-only
probe, while this module stores only anonymous qualification summaries.  Raw
payloads, metadata, exceptions, addresses, and credentials are never written.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import json
import math
import os
from pathlib import Path
from queue import Empty, Queue
import re
import sqlite3
import stat
from threading import Thread
import time
from typing import Protocol

from hedp.storage import RawData
from hedp.observations import Quality

from .read_only_qualification import (
    SUPPORTED_SOURCES,
    OfflineQualificationReport,
    ReadOnlyOfflineQualificationChecker,
)


_SAFE_REF = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_DATABASE_SUFFIX = ".qualification.sqlite3"
_SCHEMA_VERSION = "2"
_QUALITY_VALUES = frozenset(item.value for item in Quality)
_RECOVERY_STATUSES = frozenset(
    {"not_observed", "not_required", "recovered", "not_recovered"}
)
_ALLOWED_REASON_CODES = frozenset(
    {
        "attempt_budget_exceeded",
        "credential_value_present",
        "database_size_limit_exceeded",
        "evidence_invalid",
        "fingerprint_only_policy_missing",
        "forbidden_key_present",
        "metadata_not_json_safe",
        "network_address_present",
        "nonfinite_number_present",
        "payload_not_json_safe",
        "payload_too_large",
        "probe_failed",
        "qualification_reason_unrecognized",
        "quality_value_invalid",
        "recovery_not_completed",
        "rediscovery_budget_exceeded",
        "required_payload_key_missing",
        "run_deadline_exceeded",
        "sample_missed_after_resume",
        "sample_timeout",
        "source_mismatch",
        "source_not_supported",
        "timestamp_not_timezone_aware",
    }
)
_ALLOWED_SAMPLE_STATUSES = frozenset(
    {
        "deadline_exceeded",
        "missed",
        "not_qualified",
        "probe_error",
        "qualified",
        "timeout",
    }
)
_EXPECTED_COLUMNS = {
    "qualification_meta": ("purpose", "schema_version"),
    "qualification_runs": (
        "run_id",
        "source",
        "stage",
        "plan_json",
        "status",
        "failure_reason",
        "next_sample_index",
        "started_at",
        "updated_at",
    ),
    "qualification_samples": (
        "run_id",
        "sample_index",
        "scheduled_at",
        "recorded_at",
        "status",
        "reason_codes_json",
        "payload_bytes",
        "evidence_count",
        "elapsed_ms",
        "attempt_count",
        "rediscovery_attempt_count",
        "recovery_status",
        "recovery_elapsed_ms",
        "quality_counts_json",
    ),
}


class QualificationStage(str, Enum):
    SINGLE = "single"
    SHORT = "short"
    DAY_24 = "day_24"


class QualificationRunStatus(str, Enum):
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    FAILED = "failed"


class QualificationProbe(Protocol):
    """Injected read-only probe. It must not expose an operation method."""

    def collect(self) -> RawData | QualificationProbeResult: ...


@dataclass(frozen=True)
class QualificationProbeResult:
    """Raw observation plus fixed-vocabulary, anonymous transport evidence."""

    raw_data: RawData
    attempt_count: int = 1
    rediscovery_attempt_count: int = 0
    recovery_status: str = "not_observed"
    recovery_elapsed_ms: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.raw_data, RawData):
            raise TypeError("raw_data must be RawData")
        _bounded_int("attempt_count", self.attempt_count, 1, 10)
        _bounded_int(
            "rediscovery_attempt_count",
            self.rediscovery_attempt_count,
            0,
            5,
        )
        if self.recovery_status not in _RECOVERY_STATUSES:
            raise ValueError("recovery_status is not recognized")
        _bounded_int(
            "recovery_elapsed_ms",
            self.recovery_elapsed_ms,
            0,
            300_000,
        )
        if (
            self.recovery_status in {"not_observed", "not_required"}
            and self.recovery_elapsed_ms != 0
        ):
            raise ValueError(
                "recovery_elapsed_ms must be zero when recovery was not measured"
            )


@dataclass(frozen=True)
class QualificationPlan:
    run_id: str
    source: str
    stage: QualificationStage
    started_at: datetime
    duration: timedelta
    sample_interval: timedelta
    maximum_samples: int
    per_sample_timeout_seconds: float
    maximum_failures: int = 3
    maximum_database_bytes: int = 8 * 1024 * 1024
    maximum_failure_evidence: int = 20
    maximum_attempts_per_sample: int = 1
    maximum_rediscovery_attempts_per_sample: int = 0

    def __post_init__(self) -> None:
        _safe_ref("run_id", self.run_id)
        if self.source not in SUPPORTED_SOURCES:
            raise ValueError("source is not supported by the qualification checker")
        if not isinstance(self.stage, QualificationStage):
            raise TypeError("stage must be a QualificationStage")
        _aware("started_at", self.started_at)
        if not isinstance(self.duration, timedelta) or self.duration <= timedelta(0):
            raise ValueError("duration must be positive")
        if not isinstance(
            self.sample_interval, timedelta
        ) or self.sample_interval <= timedelta(0):
            raise ValueError("sample_interval must be positive")
        if self.sample_interval > self.duration:
            raise ValueError("sample_interval must not exceed duration")
        _bounded_int("maximum_samples", self.maximum_samples, 1, 2_000)
        if (
            isinstance(self.per_sample_timeout_seconds, bool)
            or not isinstance(self.per_sample_timeout_seconds, (int, float))
            or not 0 < self.per_sample_timeout_seconds <= 300
        ):
            raise ValueError(
                "per_sample_timeout_seconds must be greater than 0 and at most 300"
            )
        if self.per_sample_timeout_seconds > self.sample_interval.total_seconds():
            raise ValueError("per-sample timeout must not exceed sample_interval")
        _bounded_int("maximum_failures", self.maximum_failures, 1, 100)
        if self.maximum_failures > self.maximum_samples:
            raise ValueError("maximum_failures must not exceed maximum_samples")
        _bounded_int(
            "maximum_database_bytes",
            self.maximum_database_bytes,
            16 * 1024,
            64 * 1024 * 1024,
        )
        _bounded_int(
            "maximum_failure_evidence",
            self.maximum_failure_evidence,
            1,
            100,
        )
        _bounded_int(
            "maximum_attempts_per_sample",
            self.maximum_attempts_per_sample,
            1,
            10,
        )
        _bounded_int(
            "maximum_rediscovery_attempts_per_sample",
            self.maximum_rediscovery_attempts_per_sample,
            0,
            5,
        )
        if (
            self.maximum_rediscovery_attempts_per_sample
            > self.maximum_attempts_per_sample
        ):
            raise ValueError(
                "maximum rediscovery attempts must not exceed maximum attempts"
            )
        expected = math.ceil(self.duration / self.sample_interval)
        if self.maximum_samples != expected:
            raise ValueError("maximum_samples must match duration/sample_interval")
        if self.stage is QualificationStage.SINGLE:
            if self.maximum_samples != 1 or self.duration > timedelta(minutes=5):
                raise ValueError(
                    "single stage must contain one sample within 5 minutes"
                )
        elif self.stage is QualificationStage.SHORT:
            if not timedelta(minutes=10) <= self.duration <= timedelta(minutes=30):
                raise ValueError(
                    "short stage duration must be between 10 and 30 minutes"
                )
        elif self.duration != timedelta(hours=24):
            raise ValueError("day_24 stage duration must be exactly 24 hours")

    @classmethod
    def single(
        cls,
        *,
        run_id: str,
        source: str,
        started_at: datetime,
        per_sample_timeout_seconds: float = 30,
    ) -> QualificationPlan:
        return cls(
            run_id,
            source,
            QualificationStage.SINGLE,
            started_at,
            timedelta(seconds=per_sample_timeout_seconds),
            timedelta(seconds=per_sample_timeout_seconds),
            1,
            per_sample_timeout_seconds,
            maximum_failures=1,
        )

    @classmethod
    def short(
        cls,
        *,
        run_id: str,
        source: str,
        started_at: datetime,
        duration: timedelta = timedelta(minutes=10),
        sample_interval: timedelta = timedelta(minutes=1),
        per_sample_timeout_seconds: float = 30,
        maximum_failures: int = 3,
    ) -> QualificationPlan:
        return cls(
            run_id,
            source,
            QualificationStage.SHORT,
            started_at,
            duration,
            sample_interval,
            math.ceil(duration / sample_interval),
            per_sample_timeout_seconds,
            maximum_failures,
        )

    @classmethod
    def day_24(
        cls,
        *,
        run_id: str,
        source: str,
        started_at: datetime,
        sample_interval: timedelta = timedelta(minutes=5),
        per_sample_timeout_seconds: float = 30,
        maximum_failures: int = 3,
    ) -> QualificationPlan:
        duration = timedelta(hours=24)
        return cls(
            run_id,
            source,
            QualificationStage.DAY_24,
            started_at,
            duration,
            sample_interval,
            math.ceil(duration / sample_interval),
            per_sample_timeout_seconds,
            maximum_failures,
        )


@dataclass(frozen=True)
class FailureEvidence:
    sample_index: int
    status: str
    reason_codes: tuple[str, ...]
    recorded_at: str

    def as_dict(self) -> dict[str, object]:
        return {
            "sample_index": self.sample_index,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True)
class QualificationRunSummary:
    run_id: str
    source: str
    stage: QualificationStage
    status: QualificationRunStatus
    expected_samples: int
    recorded_samples: int
    qualified_samples: int
    failed_samples: int
    next_sample_index: int
    started_at: str
    updated_at: str
    status_counts: tuple[tuple[str, int], ...]
    success_rate: float
    latency_p50_ms: int
    latency_p95_ms: int
    latency_max_ms: int
    quality_counts: tuple[tuple[str, int], ...]
    total_attempts: int
    maximum_attempts: int
    total_rediscovery_attempts: int
    recovery_counts: tuple[tuple[str, int], ...]
    recovery_p95_ms: int
    recovery_max_ms: int
    maximum_consecutive_failed_samples: int
    failure_evidence: tuple[FailureEvidence, ...]
    omitted_failure_evidence: int

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "source": self.source,
            "stage": self.stage.value,
            "status": self.status.value,
            "expected_samples": self.expected_samples,
            "recorded_samples": self.recorded_samples,
            "qualified_samples": self.qualified_samples,
            "failed_samples": self.failed_samples,
            "next_sample_index": self.next_sample_index,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "status_counts": dict(self.status_counts),
            "success_rate": self.success_rate,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "latency_max_ms": self.latency_max_ms,
            "quality_counts": dict(self.quality_counts),
            "total_attempts": self.total_attempts,
            "maximum_attempts": self.maximum_attempts,
            "total_rediscovery_attempts": self.total_rediscovery_attempts,
            "recovery_counts": dict(self.recovery_counts),
            "recovery_p95_ms": self.recovery_p95_ms,
            "recovery_max_ms": self.recovery_max_ms,
            "maximum_consecutive_failed_samples": (
                self.maximum_consecutive_failed_samples
            ),
            "failure_evidence": [item.as_dict() for item in self.failure_evidence],
            "omitted_failure_evidence": self.omitted_failure_evidence,
        }


class QualificationTestStore:
    """SQLite store that refuses production-looking or unrelated databases."""

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path):
            raise TypeError("path must be a pathlib.Path")
        if not path.name.endswith(_DATABASE_SUFFIX):
            raise ValueError(
                f"qualification database name must end with {_DATABASE_SUFFIX}"
            )
        if not path.parent.is_dir():
            raise ValueError("qualification database parent must already exist")
        self.path = path
        guard_fd, created = _open_guarded_file(path)
        self._guard_fd: int | None = guard_fd
        try:
            self._connection = sqlite3.connect(path)
            self._connection.row_factory = sqlite3.Row
            self._configure_connection()
            _verify_file_identity(path, guard_fd)
            if created:
                self._initialize()
            else:
                self._verify_existing()
            _verify_file_identity(path, guard_fd)
            _verify_file_permissions(guard_fd)
        except Exception:
            connection = getattr(self, "_connection", None)
            if connection is not None:
                connection.close()
            os.close(guard_fd)
            self._guard_fd = None
            raise

    def close(self) -> None:
        self._connection.close()
        if self._guard_fd is not None:
            os.close(self._guard_fd)
            self._guard_fd = None

    def database_bytes(self) -> int:
        if self._guard_fd is None:
            raise RuntimeError("qualification database is closed")
        return os.fstat(self._guard_fd).st_size

    def __enter__(self) -> QualificationTestStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _configure_connection(self) -> None:
        self._connection.execute("PRAGMA foreign_keys = ON")
        enabled = self._connection.execute("PRAGMA foreign_keys").fetchone()
        if enabled is None or int(enabled[0]) != 1:
            raise RuntimeError("SQLite foreign key enforcement is unavailable")

    def _initialize(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE qualification_meta (
                purpose TEXT NOT NULL,
                schema_version TEXT NOT NULL
            );
            CREATE TABLE qualification_runs (
                run_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                stage TEXT NOT NULL,
                plan_json TEXT NOT NULL,
                status TEXT NOT NULL,
                failure_reason TEXT,
                next_sample_index INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE qualification_samples (
                run_id TEXT NOT NULL,
                sample_index INTEGER NOT NULL,
                scheduled_at TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                status TEXT NOT NULL,
                reason_codes_json TEXT NOT NULL,
                payload_bytes INTEGER NOT NULL,
                evidence_count INTEGER NOT NULL,
                elapsed_ms INTEGER NOT NULL,
                attempt_count INTEGER NOT NULL,
                rediscovery_attempt_count INTEGER NOT NULL,
                recovery_status TEXT NOT NULL,
                recovery_elapsed_ms INTEGER NOT NULL,
                quality_counts_json TEXT NOT NULL,
                PRIMARY KEY (run_id, sample_index),
                FOREIGN KEY (run_id) REFERENCES qualification_runs(run_id)
            );
            """
        )
        self._connection.execute(
            "INSERT INTO qualification_meta(purpose, schema_version) VALUES (?, ?)",
            ("read_only_qualification_test_only", _SCHEMA_VERSION),
        )
        self._connection.commit()
        self._verify_schema()

    def _verify_existing(self) -> None:
        try:
            rows = self._connection.execute(
                "SELECT purpose, schema_version FROM qualification_meta"
            ).fetchall()
        except sqlite3.Error as error:
            raise ValueError(
                "existing database is not a qualification test DB"
            ) from error
        if (
            len(rows) != 1
            or rows[0]["purpose"] != "read_only_qualification_test_only"
            or rows[0]["schema_version"] != _SCHEMA_VERSION
        ):
            raise ValueError("existing database is not a qualification test DB")
        self._verify_schema()

    def _verify_schema(self) -> None:
        try:
            table_rows = self._connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            if {str(row["name"]) for row in table_rows} != set(_EXPECTED_COLUMNS):
                raise ValueError(
                    "existing database has an unexpected qualification schema"
                )
            for table_name, expected in _EXPECTED_COLUMNS.items():
                rows = self._connection.execute(
                    f"PRAGMA table_info({table_name})"
                ).fetchall()
                if tuple(str(row["name"]) for row in rows) != expected:
                    raise ValueError(
                        "existing database has an unexpected qualification schema"
                    )
            foreign_keys = self._connection.execute(
                "PRAGMA foreign_key_list(qualification_samples)"
            ).fetchall()
            if not any(
                row["table"] == "qualification_runs"
                and row["from"] == "run_id"
                and row["to"] == "run_id"
                for row in foreign_keys
            ):
                raise ValueError(
                    "existing database has an unexpected qualification schema"
                )
            integrity = self._connection.execute("PRAGMA quick_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise ValueError("existing qualification database is corrupt")
        except sqlite3.Error as error:
            raise ValueError(
                "existing database has an unexpected qualification schema"
            ) from error

    def start_or_resume(self, plan: QualificationPlan, now: datetime) -> int:
        _aware("now", now)
        plan_json = _plan_json(plan)
        row = self._connection.execute(
            "SELECT plan_json, status, next_sample_index "
            "FROM qualification_runs WHERE run_id = ?",
            (plan.run_id,),
        ).fetchone()
        if row is None:
            self._connection.execute(
                "INSERT INTO qualification_runs("
                "run_id, source, stage, plan_json, status, failure_reason, "
                "next_sample_index, started_at, updated_at"
                ") VALUES (?, ?, ?, ?, ?, NULL, 0, ?, ?)",
                (
                    plan.run_id,
                    plan.source,
                    plan.stage.value,
                    plan_json,
                    QualificationRunStatus.RUNNING.value,
                    _timestamp(plan.started_at),
                    _timestamp(now),
                ),
            )
            self._connection.commit()
            return 0
        if row["plan_json"] != plan_json:
            raise ValueError("resume plan does not match the stored run")
        status = _stored_run_status(row["status"])
        next_index = _stored_sample_index(
            row["next_sample_index"],
            plan.maximum_samples,
        )
        if status in {
            QualificationRunStatus.COMPLETED,
            QualificationRunStatus.FAILED,
        }:
            return next_index
        self.set_run_status(plan.run_id, QualificationRunStatus.RUNNING, now)
        return next_index

    def record_sample(
        self,
        *,
        plan: QualificationPlan,
        sample_index: int,
        scheduled_at: datetime,
        recorded_at: datetime,
        status: str,
        reason_codes: tuple[str, ...],
        payload_bytes: int,
        evidence_count: int,
        elapsed_ms: int,
        attempt_count: int = 0,
        rediscovery_attempt_count: int = 0,
        recovery_status: str = "not_observed",
        recovery_elapsed_ms: int = 0,
        quality_counts: dict[str, int] | None = None,
    ) -> None:
        safe_reasons = tuple(_safe_reason(value) for value in reason_codes[:100])
        safe_status = _safe_sample_status(status)
        _bounded_int("attempt_count", attempt_count, 0, 10)
        _bounded_int(
            "rediscovery_attempt_count",
            rediscovery_attempt_count,
            0,
            5,
        )
        safe_recovery_status = _safe_recovery_status(recovery_status)
        _bounded_int(
            "recovery_elapsed_ms",
            recovery_elapsed_ms,
            0,
            300_000,
        )
        safe_quality_counts = _safe_quality_counts(quality_counts or {})
        self._connection.execute(
            "INSERT INTO qualification_samples("
            "run_id, sample_index, scheduled_at, recorded_at, status, "
            "reason_codes_json, payload_bytes, evidence_count, elapsed_ms, "
            "attempt_count, rediscovery_attempt_count, recovery_status, "
            "recovery_elapsed_ms, quality_counts_json"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                plan.run_id,
                sample_index,
                _timestamp(scheduled_at),
                _timestamp(recorded_at),
                safe_status,
                json.dumps(safe_reasons, separators=(",", ":")),
                payload_bytes,
                evidence_count,
                elapsed_ms,
                attempt_count,
                rediscovery_attempt_count,
                safe_recovery_status,
                recovery_elapsed_ms,
                json.dumps(
                    safe_quality_counts,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )
        self._connection.execute(
            "UPDATE qualification_runs SET next_sample_index = ?, updated_at = ? "
            "WHERE run_id = ?",
            (sample_index + 1, _timestamp(recorded_at), plan.run_id),
        )
        self._connection.commit()

    def set_run_status(
        self,
        run_id: str,
        status: QualificationRunStatus,
        now: datetime,
        *,
        failure_reason: str | None = None,
    ) -> None:
        self._connection.execute(
            "UPDATE qualification_runs SET status = ?, failure_reason = ?, "
            "updated_at = ? "
            "WHERE run_id = ?",
            (
                status.value,
                None if failure_reason is None else _safe_reason(failure_reason),
                _timestamp(now),
                run_id,
            ),
        )
        self._connection.commit()

    def summary(self, plan: QualificationPlan) -> QualificationRunSummary:
        run = self._connection.execute(
            "SELECT * FROM qualification_runs WHERE run_id = ?",
            (plan.run_id,),
        ).fetchone()
        if run is None:
            raise ValueError("qualification run does not exist")
        samples = self._connection.execute(
            "SELECT sample_index, recorded_at, status, reason_codes_json, "
            "elapsed_ms, attempt_count, rediscovery_attempt_count, "
            "recovery_status, recovery_elapsed_ms, quality_counts_json "
            "FROM qualification_samples WHERE run_id = ? ORDER BY sample_index",
            (plan.run_id,),
        ).fetchall()
        sanitized = [
            (
                row,
                _safe_sample_status(str(row["status"])),
                _safe_stored_reasons(row["reason_codes_json"]),
            )
            for row in samples
        ]
        counts = Counter(status for _, status, _ in sanitized)
        failed = [item for item in sanitized if item[1] != "qualified"]
        evidence_items = [
            FailureEvidence(
                int(row["sample_index"]),
                status,
                reasons,
                _safe_stored_timestamp(row["recorded_at"]),
            )
            for row, status, reasons in failed
        ]
        if run["failure_reason"] is not None:
            evidence_items.append(
                FailureEvidence(
                    int(run["next_sample_index"]),
                    "run_failed",
                    (_safe_reason(str(run["failure_reason"])),),
                    _safe_stored_timestamp(run["updated_at"]),
                )
            )
            counts["run_failed"] += 1
        evidence = tuple(evidence_items[: plan.maximum_failure_evidence])
        latencies = sorted(max(0, int(row["elapsed_ms"])) for row in samples)
        attempts = [_stored_bounded_int(row["attempt_count"], 0, 10) for row in samples]
        rediscovery_attempts = [
            _stored_bounded_int(row["rediscovery_attempt_count"], 0, 5)
            for row in samples
        ]
        recovery_counts = Counter(
            _safe_recovery_status(str(row["recovery_status"])) for row in samples
        )
        recovery_latencies = sorted(
            _stored_bounded_int(row["recovery_elapsed_ms"], 0, 300_000)
            for row in samples
            if _safe_recovery_status(str(row["recovery_status"]))
            in {"recovered", "not_recovered"}
        )
        quality_counts: Counter[str] = Counter()
        for row in samples:
            quality_counts.update(
                _safe_stored_quality_counts(row["quality_counts_json"])
            )
        qualified_samples = counts.get("qualified", 0)
        return QualificationRunSummary(
            run_id=plan.run_id,
            source=plan.source,
            stage=plan.stage,
            status=_stored_run_status(run["status"]),
            expected_samples=plan.maximum_samples,
            recorded_samples=len(samples),
            qualified_samples=qualified_samples,
            failed_samples=len(evidence_items),
            next_sample_index=_stored_sample_index(
                run["next_sample_index"],
                plan.maximum_samples,
            ),
            started_at=_safe_stored_timestamp(run["started_at"]),
            updated_at=_safe_stored_timestamp(run["updated_at"]),
            status_counts=tuple(sorted(counts.items())),
            success_rate=(
                qualified_samples / len(samples) if samples else 0.0
            ),
            latency_p50_ms=_nearest_rank(latencies, 0.50),
            latency_p95_ms=_nearest_rank(latencies, 0.95),
            latency_max_ms=latencies[-1] if latencies else 0,
            quality_counts=tuple(sorted(quality_counts.items())),
            total_attempts=sum(attempts),
            maximum_attempts=max(attempts, default=0),
            total_rediscovery_attempts=sum(rediscovery_attempts),
            recovery_counts=tuple(sorted(recovery_counts.items())),
            recovery_p95_ms=_nearest_rank(recovery_latencies, 0.95),
            recovery_max_ms=(
                recovery_latencies[-1] if recovery_latencies else 0
            ),
            maximum_consecutive_failed_samples=_maximum_failed_run(
                tuple(status for _, status, _ in sanitized)
            ),
            failure_evidence=evidence,
            omitted_failure_evidence=max(0, len(evidence_items) - len(evidence)),
        )


class ReadOnlyQualificationHarness:
    """Run finite qualification samples with resumable anonymous evidence."""

    def __init__(
        self,
        store: QualificationTestStore,
        *,
        checker: ReadOnlyOfflineQualificationChecker | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        sleeper: Callable[[float], None] = time.sleep,
        maximum_sleep_slice_seconds: float = 60,
    ) -> None:
        if (
            isinstance(maximum_sleep_slice_seconds, bool)
            or not isinstance(maximum_sleep_slice_seconds, (int, float))
            or not 0 < maximum_sleep_slice_seconds <= 60
        ):
            raise ValueError(
                "maximum_sleep_slice_seconds must be greater than 0 and at most 60"
            )
        self._store = store
        self._checker = checker or ReadOnlyOfflineQualificationChecker()
        self._clock = clock
        self._sleeper = sleeper
        self._maximum_sleep_slice_seconds = maximum_sleep_slice_seconds

    def run(
        self,
        plan: QualificationPlan,
        probe: QualificationProbe,
        *,
        stop_requested: Callable[[], bool] = lambda: False,
    ) -> QualificationRunSummary:
        now = self._now()
        if now < plan.started_at:
            raise ValueError("qualification run cannot start in the future")
        next_index = self._store.start_or_resume(plan, now)
        existing = self._store.summary(plan)
        if existing.status in {
            QualificationRunStatus.COMPLETED,
            QualificationRunStatus.FAILED,
        }:
            return existing
        failures = existing.failed_samples
        deadline = plan.started_at + plan.duration

        while next_index < plan.maximum_samples:
            if stop_requested():
                self._store.set_run_status(
                    plan.run_id,
                    QualificationRunStatus.INTERRUPTED,
                    self._now(),
                )
                return self._store.summary(plan)

            scheduled_at = plan.started_at + plan.sample_interval * next_index
            now = self._now()
            if now >= deadline:
                self._record_failure(
                    plan,
                    next_index,
                    scheduled_at,
                    now,
                    "deadline_exceeded",
                    ("run_deadline_exceeded",),
                )
                self._store.set_run_status(
                    plan.run_id,
                    QualificationRunStatus.FAILED,
                    now,
                )
                return self._store.summary(plan)

            if now < scheduled_at:
                self._sleeper(
                    min(
                        (scheduled_at - now).total_seconds(),
                        self._maximum_sleep_slice_seconds,
                    )
                )
                continue

            if now - scheduled_at >= plan.sample_interval:
                self._record_failure(
                    plan,
                    next_index,
                    scheduled_at,
                    now,
                    "missed",
                    ("sample_missed_after_resume",),
                )
                failures += 1
            else:
                sample = _collect_with_timeout(
                    probe,
                    plan.per_sample_timeout_seconds,
                )
                recorded_at = self._now()
                if recorded_at >= deadline:
                    self._record_failure(
                        plan,
                        next_index,
                        scheduled_at,
                        recorded_at,
                        "deadline_exceeded",
                        ("run_deadline_exceeded",),
                        elapsed_ms=sample.elapsed_ms,
                    )
                    self._store.set_run_status(
                        plan.run_id,
                        QualificationRunStatus.FAILED,
                        recorded_at,
                    )
                    return self._store.summary(plan)
                if sample.result is None:
                    self._record_failure(
                        plan,
                        next_index,
                        scheduled_at,
                        recorded_at,
                        sample.status,
                        (sample.reason_code,),
                        elapsed_ms=sample.elapsed_ms,
                    )
                    failures += 1
                    if sample.status == "timeout":
                        self._store.set_run_status(
                            plan.run_id,
                            QualificationRunStatus.FAILED,
                            recorded_at,
                        )
                        return self._store.summary(plan)
                else:
                    probe_result = sample.result
                    report = self._checker.evaluate(probe_result.raw_data)
                    if report.source != plan.source:
                        report = OfflineQualificationReport(
                            "not_qualified",
                            plan.source,
                            ("source_mismatch",),
                            report.payload_bytes,
                            report.evidence_count,
                        )
                    operational_reasons: list[str] = []
                    if (
                        probe_result.attempt_count
                        > plan.maximum_attempts_per_sample
                    ):
                        operational_reasons.append("attempt_budget_exceeded")
                    if (
                        probe_result.rediscovery_attempt_count
                        > plan.maximum_rediscovery_attempts_per_sample
                    ):
                        operational_reasons.append(
                            "rediscovery_budget_exceeded"
                        )
                    if probe_result.recovery_status == "not_recovered":
                        operational_reasons.append("recovery_not_completed")
                    status = (
                        "qualified"
                        if (
                            report.status == "qualified"
                            and not operational_reasons
                        )
                        else "not_qualified"
                    )
                    self._store.record_sample(
                        plan=plan,
                        sample_index=next_index,
                        scheduled_at=scheduled_at,
                        recorded_at=recorded_at,
                        status=status,
                        reason_codes=(
                            *report.reasons,
                            *operational_reasons,
                        ),
                        payload_bytes=report.payload_bytes,
                        evidence_count=report.evidence_count,
                        elapsed_ms=sample.elapsed_ms,
                        attempt_count=probe_result.attempt_count,
                        rediscovery_attempt_count=(
                            probe_result.rediscovery_attempt_count
                        ),
                        recovery_status=probe_result.recovery_status,
                        recovery_elapsed_ms=(
                            probe_result.recovery_elapsed_ms
                        ),
                        quality_counts=_quality_counts(
                            probe_result.raw_data.payload
                        ),
                    )
                    if status != "qualified":
                        failures += 1

            if self._database_too_large(plan):
                self._store.set_run_status(
                    plan.run_id,
                    QualificationRunStatus.FAILED,
                    self._now(),
                    failure_reason="database_size_limit_exceeded",
                )
                return self._store.summary(plan)
            next_index += 1
            if failures >= plan.maximum_failures:
                self._store.set_run_status(
                    plan.run_id,
                    QualificationRunStatus.FAILED,
                    self._now(),
                )
                return self._store.summary(plan)

        final_summary = self._store.summary(plan)
        final = (
            QualificationRunStatus.COMPLETED
            if _accepts_completed_run(plan, final_summary)
            else QualificationRunStatus.FAILED
        )
        self._store.set_run_status(plan.run_id, final, self._now())
        return self._store.summary(plan)

    def _record_failure(
        self,
        plan: QualificationPlan,
        sample_index: int,
        scheduled_at: datetime,
        recorded_at: datetime,
        status: str,
        reason_codes: tuple[str, ...],
        *,
        elapsed_ms: int = 0,
    ) -> None:
        self._store.record_sample(
            plan=plan,
            sample_index=sample_index,
            scheduled_at=scheduled_at,
            recorded_at=recorded_at,
            status=status,
            reason_codes=reason_codes,
            payload_bytes=0,
            evidence_count=0,
            elapsed_ms=elapsed_ms,
        )

    def _database_too_large(self, plan: QualificationPlan) -> bool:
        return self._store.database_bytes() > plan.maximum_database_bytes

    def _now(self) -> datetime:
        value = self._clock()
        _aware("clock result", value)
        return value


@dataclass(frozen=True)
class _ProbeSample:
    result: QualificationProbeResult | None
    status: str
    reason_code: str
    elapsed_ms: int


def _collect_with_timeout(
    probe: QualificationProbe,
    timeout_seconds: float,
) -> _ProbeSample:
    result: Queue[tuple[str, object]] = Queue(maxsize=1)
    started = time.monotonic()

    def collect() -> None:
        try:
            value = probe.collect()
        except Exception:
            result.put(("probe_error", None))
            return
        result.put(("ok", value))

    worker = Thread(target=collect, daemon=True, name="read-only-qualification-probe")
    worker.start()
    worker.join(timeout_seconds)
    elapsed_ms = max(0, int((time.monotonic() - started) * 1_000))
    if worker.is_alive():
        return _ProbeSample(None, "timeout", "sample_timeout", elapsed_ms)
    try:
        status, value = result.get_nowait()
    except Empty:
        return _ProbeSample(None, "probe_error", "probe_failed", elapsed_ms)
    if status != "ok":
        return _ProbeSample(None, "probe_error", "probe_failed", elapsed_ms)
    if isinstance(value, RawData):
        value = QualificationProbeResult(value)
    if not isinstance(value, QualificationProbeResult):
        return _ProbeSample(None, "probe_error", "probe_failed", elapsed_ms)
    return _ProbeSample(value, "qualified", "", elapsed_ms)


def _plan_json(plan: QualificationPlan) -> str:
    return json.dumps(
        {
            "source": plan.source,
            "stage": plan.stage.value,
            "started_at": _timestamp(plan.started_at),
            "duration_seconds": plan.duration.total_seconds(),
            "sample_interval_seconds": plan.sample_interval.total_seconds(),
            "maximum_samples": plan.maximum_samples,
            "per_sample_timeout_seconds": plan.per_sample_timeout_seconds,
            "maximum_failures": plan.maximum_failures,
            "maximum_database_bytes": plan.maximum_database_bytes,
            "maximum_failure_evidence": plan.maximum_failure_evidence,
            "maximum_attempts_per_sample": plan.maximum_attempts_per_sample,
            "maximum_rediscovery_attempts_per_sample": (
                plan.maximum_rediscovery_attempts_per_sample
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _timestamp(value: datetime) -> str:
    _aware("timestamp", value)
    return value.astimezone(timezone.utc).isoformat()


def _aware(name: str, value: datetime) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _open_guarded_file(path: Path) -> tuple[int, bool]:
    flags = (
        os.O_RDWR
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        file_descriptor = os.open(
            path,
            flags | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        created = True
    except FileExistsError:
        if path.is_symlink():
            raise ValueError("qualification database must not be a symlink") from None
        try:
            file_descriptor = os.open(path, flags)
        except OSError as error:
            raise ValueError(
                "qualification database cannot be opened safely"
            ) from error
        created = False
    except OSError as error:
        raise ValueError("qualification database cannot be created safely") from error
    try:
        _verify_file_identity(path, file_descriptor)
    except Exception:
        os.close(file_descriptor)
        raise
    return file_descriptor, created


def _verify_file_identity(path: Path, file_descriptor: int) -> None:
    try:
        opened = os.fstat(file_descriptor)
        current = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise ValueError("qualification database path changed while opening") from error
    if (
        not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(current.st_mode)
        or not os.path.samestat(opened, current)
    ):
        raise ValueError("qualification database path changed while opening")


def _verify_file_permissions(file_descriptor: int) -> None:
    if os.name != "posix":
        return
    mode = stat.S_IMODE(os.fstat(file_descriptor).st_mode)
    if mode != stat.S_IRUSR | stat.S_IWUSR:
        raise PermissionError("qualification database permissions must be 0600")


def _safe_ref(name: str, value: str) -> None:
    if not isinstance(value, str) or _SAFE_REF.fullmatch(value) is None:
        raise ValueError(f"{name} must be a safe opaque reference")


def _safe_reason(value: str) -> str:
    if isinstance(value, str) and value in _ALLOWED_REASON_CODES:
        return value
    return "qualification_reason_unrecognized"


def _safe_sample_status(value: str) -> str:
    if isinstance(value, str) and value in _ALLOWED_SAMPLE_STATUSES:
        return value
    return "not_qualified"


def _safe_recovery_status(value: str) -> str:
    if isinstance(value, str) and value in _RECOVERY_STATUSES:
        return value
    return "not_observed"


def _quality_counts(value: object) -> dict[str, int]:
    counts: Counter[str] = Counter()

    def visit(item: object) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                if key == "quality" and isinstance(nested, str):
                    if nested in _QUALITY_VALUES:
                        counts[nested] += 1
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return dict(sorted(counts.items()))


def _safe_quality_counts(value: dict[str, int]) -> dict[str, int]:
    safe: dict[str, int] = {}
    for quality, count in value.items():
        if quality not in _QUALITY_VALUES:
            continue
        if isinstance(count, bool) or not isinstance(count, int):
            continue
        if 0 <= count <= 1_000_000:
            safe[quality] = count
    return dict(sorted(safe.items()))


def _safe_stored_quality_counts(value: object) -> dict[str, int]:
    if not isinstance(value, str):
        return {}
    try:
        counts = json.loads(value)
    except (TypeError, ValueError):
        return {}
    if not isinstance(counts, dict):
        return {}
    return _safe_quality_counts(counts)


def _safe_stored_reasons(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ("qualification_reason_unrecognized",)
    try:
        reasons = json.loads(value)
    except (TypeError, ValueError):
        return ("qualification_reason_unrecognized",)
    if not isinstance(reasons, list):
        return ("qualification_reason_unrecognized",)
    return tuple(_safe_reason(reason) for reason in reasons[:100])


def _safe_stored_timestamp(value: object) -> str:
    if not isinstance(value, str):
        return "invalid_timestamp"
    try:
        parsed = datetime.fromisoformat(value)
        _aware("stored timestamp", parsed)
    except (TypeError, ValueError):
        return "invalid_timestamp"
    return _timestamp(parsed)


def _stored_run_status(value: object) -> QualificationRunStatus:
    try:
        return QualificationRunStatus(value)
    except (TypeError, ValueError):
        raise ValueError("stored qualification status is invalid") from None


def _stored_sample_index(value: object, maximum_samples: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("stored qualification sample index is invalid")
    if not 0 <= value <= maximum_samples:
        raise ValueError("stored qualification sample index is invalid")
    return value


def _stored_bounded_int(value: object, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("stored qualification metric is invalid")
    if not minimum <= value <= maximum:
        raise ValueError("stored qualification metric is invalid")
    return value


def _bounded_int(name: str, value: int, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")


def _nearest_rank(values: list[int], quantile: float) -> int:
    if not values:
        return 0
    rank = max(1, math.ceil(len(values) * quantile))
    return values[min(rank - 1, len(values) - 1)]


def _maximum_failed_run(statuses: tuple[str, ...]) -> int:
    maximum = 0
    current = 0
    for status in statuses:
        if status == "qualified":
            current = 0
            continue
        current += 1
        maximum = max(maximum, current)
    return maximum


def _accepts_completed_run(
    plan: QualificationPlan,
    summary: QualificationRunSummary,
) -> bool:
    if summary.recorded_samples != plan.maximum_samples:
        return False
    if plan.stage is not QualificationStage.DAY_24:
        return summary.failed_samples == 0
    maximum_gap = (
        plan.sample_interval * summary.maximum_consecutive_failed_samples
    )
    return summary.success_rate >= 0.99 and maximum_gap <= timedelta(minutes=15)
