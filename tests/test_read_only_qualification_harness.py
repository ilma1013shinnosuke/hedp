from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import stat
from threading import Event

import pytest

import hedp.adapters.read_only_qualification_harness as qualification_harness
from hedp.adapters.read_only_qualification import OfflineQualificationReport
from hedp.adapters.read_only_qualification_harness import (
    QualificationPlan,
    QualificationRunStatus,
    QualificationTestStore,
    ReadOnlyQualificationHarness,
)
from hedp.storage import RawData


NOW = datetime(2026, 7, 27, 0, tzinfo=timezone.utc)
SHA = "a" * 64


class FakeClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


class GoodProbe:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.calls = 0

    def collect(self) -> RawData:
        self.calls += 1
        return _valid_raw(self.clock())


def _valid_raw(timestamp: datetime = NOW) -> RawData:
    return RawData(
        "qrio_read_only",
        timestamp,
        {
            "status": {"quality": "good"},
            "health": {},
            "history": {},
            "evidence_sha256": {"status": SHA},
        },
        metadata={
            "raw_policy": "fingerprint_only_due_to_household_secrets",
        },
    )


def _valid_modbus_raw(timestamp: datetime = NOW) -> RawData:
    return RawData(
        "fusionsolar_modbus_tcp",
        timestamp,
        {
            "ranges": [
                {
                    "name": "inverter_state",
                    "function_code": 3,
                    "start_address": 32064,
                    "registers": [1, 2, 3],
                }
            ]
        },
        metadata={"target_alias": "solar-inverter"},
    )


def _store_path(tmp_path: Path, name: str = "run") -> Path:
    return tmp_path / f"{name}.qualification.sqlite3"


def _harness(
    tmp_path: Path,
    clock: FakeClock,
    *,
    name: str = "run",
) -> tuple[QualificationTestStore, ReadOnlyQualificationHarness]:
    store = QualificationTestStore(_store_path(tmp_path, name))
    harness = ReadOnlyQualificationHarness(
        store,
        clock=clock,
        sleeper=clock.sleep,
    )
    return store, harness


def test_single_run_uses_only_anonymous_summary_database(tmp_path: Path) -> None:
    clock = FakeClock()
    store, harness = _harness(tmp_path, clock)
    probe = GoodProbe(clock)
    plan = QualificationPlan.single(
        run_id="single-1",
        source="qrio_read_only",
        started_at=NOW,
    )

    summary = harness.run(plan, probe)
    store.close()

    assert summary.status is QualificationRunStatus.COMPLETED
    assert summary.recorded_samples == 1
    assert summary.qualified_samples == 1
    assert summary.failure_evidence == ()
    assert probe.calls == 1
    database_bytes = _store_path(tmp_path).read_bytes()
    assert b"evidence_sha256" not in database_bytes
    assert SHA.encode() not in database_bytes
    assert b"target_ref" not in database_bytes


def test_single_modbus_run_persists_only_anonymous_summary(
    tmp_path: Path,
) -> None:
    class ModbusProbe:
        def collect(self) -> RawData:
            return _valid_modbus_raw()

    clock = FakeClock()
    store, harness = _harness(tmp_path, clock, name="modbus")
    plan = QualificationPlan.single(
        run_id="modbus-single-1",
        source="fusionsolar_modbus_tcp",
        started_at=NOW,
    )

    summary = harness.run(plan, ModbusProbe())
    store.close()

    assert summary.status is QualificationRunStatus.COMPLETED
    assert summary.qualified_samples == 1
    database_bytes = _store_path(tmp_path, "modbus").read_bytes()
    assert b"inverter_state" not in database_bytes
    assert b"solar-inverter" not in database_bytes
    assert b"registers" not in database_bytes


def test_short_run_can_interrupt_and_resume_without_duplicate_samples(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    store, harness = _harness(tmp_path, clock)
    probe = GoodProbe(clock)
    plan = QualificationPlan.short(
        run_id="short-1",
        source="qrio_read_only",
        started_at=NOW,
    )

    interrupted = harness.run(
        plan,
        probe,
        stop_requested=lambda: probe.calls >= 3,
    )
    resumed = harness.run(plan, probe)
    store.close()

    assert interrupted.status is QualificationRunStatus.INTERRUPTED
    assert interrupted.recorded_samples == 3
    assert resumed.status is QualificationRunStatus.COMPLETED
    assert resumed.recorded_samples == plan.maximum_samples == 10
    assert probe.calls == 10


def test_short_run_preserves_missing_sample_and_later_recovery(
    tmp_path: Path,
) -> None:
    class MissingThenGoodProbe(GoodProbe):
        def collect(self) -> RawData:
            raw = super().collect()
            if self.calls != 1:
                return raw
            return RawData(
                raw.source,
                raw.timestamp,
                {
                    key: value
                    for key, value in raw.payload.items()
                    if key != "status"
                },
                metadata=raw.metadata,
            )

    clock = FakeClock()
    store, harness = _harness(tmp_path, clock, name="missing-recovery")
    probe = MissingThenGoodProbe(clock)
    plan = QualificationPlan.short(
        run_id="missing-recovery",
        source="qrio_read_only",
        started_at=NOW,
        maximum_failures=2,
    )

    summary = harness.run(plan, probe)
    with sqlite3.connect(_store_path(tmp_path, "missing-recovery")) as connection:
        statuses = [
            row[0]
            for row in connection.execute(
                "SELECT status FROM qualification_samples ORDER BY sample_index"
            )
        ]
    store.close()

    assert summary.status is QualificationRunStatus.FAILED
    assert summary.recorded_samples == plan.maximum_samples == 10
    assert summary.qualified_samples == 9
    assert summary.failure_evidence[0].reason_codes == (
        "required_payload_key_missing",
    )
    assert statuses == ["not_qualified", *(["qualified"] * 9)]


def test_24_hour_plan_completes_with_simulated_clock_not_launchd(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    store, harness = _harness(tmp_path, clock)
    probe = GoodProbe(clock)
    plan = QualificationPlan.day_24(
        run_id="day-1",
        source="qrio_read_only",
        started_at=NOW,
        sample_interval=timedelta(hours=1),
    )

    summary = harness.run(plan, probe)
    store.close()

    assert summary.status is QualificationRunStatus.COMPLETED
    assert summary.expected_samples == 24
    assert summary.qualified_samples == 24
    assert probe.calls == 24


def test_24_hour_plan_rejects_success_rate_below_99_percent(
    tmp_path: Path,
) -> None:
    class OneInvalidProbe(GoodProbe):
        def collect(self) -> RawData:
            raw = super().collect()
            if self.calls != 2:
                return raw
            return RawData(
                raw.source,
                raw.timestamp,
                {**raw.payload, "quality": "unsupported-quality"},
                metadata=raw.metadata,
            )

    clock = FakeClock()
    store, harness = _harness(tmp_path, clock, name="day-tolerant")
    probe = OneInvalidProbe(clock)
    plan = QualificationPlan.day_24(
        run_id="day-tolerant-1",
        source="qrio_read_only",
        started_at=NOW,
        sample_interval=timedelta(hours=1),
        maximum_failures=2,
    )

    summary = harness.run(plan, probe)
    store.close()

    assert summary.status is QualificationRunStatus.FAILED
    assert summary.success_rate < 0.99
    assert summary.maximum_consecutive_failed_samples == 1


def test_24_hour_acceptance_uses_99_percent_and_15_minute_gap(
    tmp_path: Path,
) -> None:
    class OneInvalidProbe(GoodProbe):
        def collect(self) -> RawData:
            raw = super().collect()
            if self.calls != 2:
                return raw
            return RawData(
                raw.source,
                raw.timestamp,
                {**raw.payload, "quality": "unsupported-quality"},
                metadata=raw.metadata,
            )

    clock = FakeClock()
    store, harness = _harness(tmp_path, clock, name="day-accepted")
    probe = OneInvalidProbe(clock)
    plan = QualificationPlan.day_24(
        run_id="day-accepted-1",
        source="qrio_read_only",
        started_at=NOW,
        sample_interval=timedelta(minutes=5),
        maximum_failures=2,
    )

    summary = harness.run(plan, probe)
    store.close()

    assert summary.status is QualificationRunStatus.COMPLETED
    assert summary.success_rate >= 0.99
    assert summary.maximum_consecutive_failed_samples == 1


def test_summary_reports_anonymous_latency_statistics(tmp_path: Path) -> None:
    clock = FakeClock()
    store, harness = _harness(tmp_path, clock, name="latency")
    summary = harness.run(
        QualificationPlan.single(
            run_id="latency-1",
            source="qrio_read_only",
            started_at=NOW,
        ),
        GoodProbe(clock),
    )
    store.close()

    assert summary.latency_p50_ms >= 0
    assert summary.latency_p95_ms >= summary.latency_p50_ms
    assert summary.latency_max_ms >= summary.latency_p95_ms
    assert summary.as_dict()["success_rate"] == 1.0


def test_resume_records_missed_slot_as_failure_evidence(tmp_path: Path) -> None:
    clock = FakeClock()
    store, harness = _harness(tmp_path, clock)
    probe = GoodProbe(clock)
    plan = QualificationPlan.short(
        run_id="short-gap",
        source="qrio_read_only",
        started_at=NOW,
        maximum_failures=3,
    )

    harness.run(plan, probe, stop_requested=lambda: probe.calls >= 1)
    clock.value += timedelta(minutes=2, seconds=30)
    summary = harness.run(plan, probe)
    store.close()

    assert summary.status is QualificationRunStatus.FAILED
    assert summary.failed_samples >= 1
    assert summary.failure_evidence[0].status == "missed"
    assert summary.failure_evidence[0].reason_codes == ("sample_missed_after_resume",)


def test_probe_timeout_is_bounded_and_exception_text_is_not_stored(
    tmp_path: Path,
) -> None:
    release = Event()
    finished = Event()

    class BlockingProbe:
        def __init__(self) -> None:
            self.calls = 0

        def collect(self) -> RawData:
            self.calls += 1
            release.wait()
            finished.set()
            return _valid_raw()

    clock = FakeClock()
    store, harness = _harness(tmp_path, clock)
    plan = QualificationPlan.short(
        run_id="timeout-1",
        source="qrio_read_only",
        started_at=NOW,
        per_sample_timeout_seconds=0.01,
        maximum_failures=3,
    )

    probe = BlockingProbe()
    summary = harness.run(plan, probe)
    release.set()
    assert finished.wait(1)
    store.close()

    assert summary.status is QualificationRunStatus.FAILED
    assert summary.recorded_samples == 1
    assert probe.calls == 1
    assert summary.failure_evidence[0].status == "timeout"
    assert summary.failure_evidence[0].reason_codes == ("sample_timeout",)


def test_probe_failure_is_sanitized_and_evidence_is_bounded(tmp_path: Path) -> None:
    private = "private-household-exception-detail"

    class FailingProbe:
        def collect(self) -> RawData:
            raise RuntimeError(private)

    clock = FakeClock()
    store, harness = _harness(tmp_path, clock)
    plan = replace(
        QualificationPlan.short(
            run_id="failures-1",
            source="qrio_read_only",
            started_at=NOW,
            maximum_failures=3,
        ),
        maximum_failure_evidence=1,
    )

    summary = harness.run(plan, FailingProbe())
    store.close()

    assert summary.status is QualificationRunStatus.FAILED
    assert summary.failed_samples == 3
    assert len(summary.failure_evidence) == 1
    assert summary.omitted_failure_evidence == 2
    assert private not in repr(summary)
    assert private.encode() not in _store_path(tmp_path).read_bytes()


def test_checker_failure_retains_only_reason_codes(tmp_path: Path) -> None:
    private = "Bearer household-secret"

    class InvalidProbe:
        def collect(self) -> RawData:
            raw = _valid_raw()
            return RawData(
                raw.source,
                raw.timestamp,
                {**raw.payload, "private_note": private},
                metadata=raw.metadata,
            )

    clock = FakeClock()
    store, harness = _harness(tmp_path, clock)
    plan = QualificationPlan.single(
        run_id="invalid-1",
        source="qrio_read_only",
        started_at=NOW,
    )

    summary = harness.run(plan, InvalidProbe())
    store.close()

    assert summary.status is QualificationRunStatus.FAILED
    assert "credential_value_present" in summary.failure_evidence[0].reason_codes
    assert private not in repr(summary)
    assert private.encode() not in _store_path(tmp_path).read_bytes()


def test_store_refuses_production_or_unrelated_database_paths(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="must end"):
        QualificationTestStore(tmp_path / "hedp.db")

    unrelated = _store_path(tmp_path, "unrelated")
    unrelated.write_text("not a qualification database", encoding="utf-8")
    with pytest.raises(ValueError, match="not a qualification"):
        QualificationTestStore(unrelated)


def test_store_uses_private_permissions_and_enforces_foreign_keys(
    tmp_path: Path,
) -> None:
    path = _store_path(tmp_path, "protected")
    store = QualificationTestStore(path)

    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert store._connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        store._connection.execute(
            "INSERT INTO qualification_samples VALUES "
            "('missing', 0, '', '', 'qualified', '[]', 0, 0, 0, "
            "1, 0, 'not_observed', 0, '{}')"
        )
    store._connection.rollback()
    store.close()
    if os.name == "posix":
        path.chmod(0o644)
        with pytest.raises(PermissionError, match="0600"):
            QualificationTestStore(path)


def test_store_rejects_symlink_empty_file_and_marker_only_schema(
    tmp_path: Path,
) -> None:
    empty = _store_path(tmp_path, "empty")
    empty.touch()
    with pytest.raises(ValueError, match="not a qualification"):
        QualificationTestStore(empty)

    target = _store_path(tmp_path, "target")
    target.touch()
    link = _store_path(tmp_path, "link")
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symlink|changed"):
        QualificationTestStore(link)

    incomplete = _store_path(tmp_path, "incomplete")
    connection = sqlite3.connect(incomplete)
    connection.execute(
        "CREATE TABLE qualification_meta "
        "(purpose TEXT NOT NULL, schema_version TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO qualification_meta VALUES "
        "('read_only_qualification_test_only', '2')"
    )
    connection.commit()
    connection.close()
    with pytest.raises(ValueError, match="unexpected qualification schema"):
        QualificationTestStore(incomplete)


@pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX permits replacing an open pathname for this race simulation",
)
def test_store_detects_path_replacement_during_sqlite_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _store_path(tmp_path, "replaced")
    original_connect = sqlite3.connect

    def replace_then_connect(
        database: str | Path,
        *args: object,
        **kwargs: object,
    ) -> sqlite3.Connection:
        Path(database).unlink()
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(
        qualification_harness.sqlite3,
        "connect",
        replace_then_connect,
    )

    with pytest.raises(ValueError, match="path changed"):
        QualificationTestStore(path)


def test_plan_bounds_reject_unbounded_or_wrong_stage_windows() -> None:
    with pytest.raises(ValueError, match="at most 300"):
        QualificationPlan.single(
            run_id="bad-timeout",
            source="qrio_read_only",
            started_at=NOW,
            per_sample_timeout_seconds=301,
        )
    with pytest.raises(ValueError, match="between 10 and 30"):
        QualificationPlan.short(
            run_id="bad-short",
            source="qrio_read_only",
            started_at=NOW,
            duration=timedelta(hours=1),
        )
    with pytest.raises(ValueError, match="must not exceed duration"):
        QualificationPlan.day_24(
            run_id="bad-interval",
            source="qrio_read_only",
            started_at=NOW,
            sample_interval=timedelta(hours=25),
        )


def test_future_start_is_rejected_without_running_probe(tmp_path: Path) -> None:
    clock = FakeClock()
    store, harness = _harness(tmp_path, clock, name="future")
    probe = GoodProbe(clock)
    plan = QualificationPlan.single(
        run_id="future-start",
        source="qrio_read_only",
        started_at=NOW + timedelta(minutes=1),
    )

    with pytest.raises(ValueError, match="future"):
        harness.run(plan, probe)
    store.close()

    assert probe.calls == 0


def test_late_initial_slot_is_missed_without_catch_up(tmp_path: Path) -> None:
    clock = FakeClock(NOW + timedelta(minutes=1))
    store, harness = _harness(tmp_path, clock, name="late-first")
    probe = GoodProbe(clock)
    plan = QualificationPlan.short(
        run_id="late-first",
        source="qrio_read_only",
        started_at=NOW,
        maximum_failures=1,
    )

    summary = harness.run(plan, probe)
    store.close()

    assert summary.status is QualificationRunStatus.FAILED
    assert summary.failure_evidence[0].status == "missed"
    assert probe.calls == 0


def test_unrecognized_checker_reason_is_redacted_from_summary_and_database(
    tmp_path: Path,
) -> None:
    private = "alice_house"

    class LeakyChecker:
        def evaluate(self, raw_data: RawData) -> OfflineQualificationReport:
            return OfflineQualificationReport(
                "not_qualified",
                raw_data.source,
                (private,),
                1,
                0,
            )

    clock = FakeClock()
    store = QualificationTestStore(_store_path(tmp_path, "reason-redaction"))
    harness = ReadOnlyQualificationHarness(
        store,
        checker=LeakyChecker(),  # type: ignore[arg-type]
        clock=clock,
        sleeper=clock.sleep,
    )
    plan = QualificationPlan.single(
        run_id="reason-redaction",
        source="qrio_read_only",
        started_at=NOW,
    )

    summary = harness.run(plan, GoodProbe(clock))
    store.close()

    assert summary.failure_evidence[0].reason_codes == (
        "qualification_reason_unrecognized",
    )
    assert private not in repr(summary)
    assert (
        private.encode() not in _store_path(tmp_path, "reason-redaction").read_bytes()
    )


def test_database_growth_limit_stops_run_with_sanitized_evidence(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    store, harness = _harness(tmp_path, clock, name="size-limit")
    probe = GoodProbe(clock)
    plan = replace(
        QualificationPlan.day_24(
            run_id="size-limit",
            source="qrio_read_only",
            started_at=NOW,
        ),
        maximum_database_bytes=16 * 1024,
    )

    summary = harness.run(plan, probe)
    store.close()

    assert summary.status is QualificationRunStatus.FAILED
    assert summary.recorded_samples < summary.expected_samples
    assert summary.failure_evidence[-1].status == "run_failed"
    assert summary.failure_evidence[-1].reason_codes == (
        "database_size_limit_exceeded",
    )
