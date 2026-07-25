from __future__ import annotations

import json
import sqlite3
import stat

import pytest

from hedp.operations.operational_metrics import (
    FailureCategory,
    OperationMetric,
    OperationName,
    OperationOutcome,
    OperationalMetricsJournal,
    ReadOnlyDatabaseMetrics,
    duration_bucket,
)
from hedp.storage import Storage


def test_duration_bucket_is_coarse_and_rejects_negative_values() -> None:
    assert duration_bucket(0) == "under_1s"
    assert duration_bucket(1) == "1_to_5s"
    assert duration_bucket(5) == "5_to_30s"
    assert duration_bucket(30) == "30s_or_more"
    with pytest.raises(ValueError, match="must not be negative"):
        duration_bucket(-0.1)


def test_operation_metric_exposes_only_fixed_anonymous_metadata() -> None:
    metric = OperationMetric.from_result(
        OperationName.DEVICE_REALTIME,
        OperationOutcome.SKIPPED,
        elapsed_seconds=0.2,
        failure_category=FailureCategory.LOCK_HELD,
    )

    assert metric.to_dict() == {
        "job": "device_realtime",
        "outcome": "skipped",
        "duration": "under_1s",
        "failure_category": "lock_held",
    }


def test_operation_metric_rejects_ambiguous_outcomes() -> None:
    with pytest.raises(ValueError, match="require a failure category"):
        OperationMetric.from_result(
            OperationName.DAILY, OperationOutcome.FAILED, 1
        )
    with pytest.raises(ValueError, match="require the timeout category"):
        OperationMetric.from_result(
            OperationName.DAILY,
            OperationOutcome.TIMED_OUT,
            1,
            FailureCategory.NETWORK,
        )


def test_readonly_database_metrics_counts_rows_without_returning_payload_or_path(tmp_path) -> None:
    database = tmp_path / "observations.db"
    storage = Storage(str(database))
    connection = storage.connect()
    connection.execute("INSERT INTO raw_data (data) VALUES ('private payload')")
    connection.execute("INSERT INTO records (data) VALUES ('private record')")
    connection.commit()
    connection.close()

    report = ReadOnlyDatabaseMetrics().collect(database).to_dict()

    assert report["status"] == "ok"
    assert report["job"] == "daily_health"
    assert report["database_bytes"] > 0
    assert report["filesystem_free_bytes"] > 0
    assert report["page_count"] is not None
    assert report["raw_data_rows"] == 1
    assert report["record_rows"] == 1
    assert "observations.db" not in repr(report)
    assert "private" not in repr(report)
    with sqlite3.connect(database) as verify:
        assert verify.execute("SELECT data FROM raw_data").fetchone()[0] == "private payload"


def test_readonly_database_metrics_handles_missing_database_without_path_or_error_text(tmp_path) -> None:
    report = ReadOnlyDatabaseMetrics().collect(tmp_path / "missing.db").to_dict()

    assert report == {
        "job": "daily_health",
        "status": "unavailable",
        "database_bytes": 0,
        "filesystem_free_bytes": 0,
        "page_count": None,
        "free_page_count": None,
        "raw_data_rows": None,
        "record_rows": None,
        "probe_duration": "under_1s",
    }


def test_operational_journal_writes_date_only_private_fixed_vocabulary(tmp_path) -> None:
    journal = OperationalMetricsJournal(tmp_path / "state")
    journal.append(
        OperationMetric.from_result(
            OperationName.SWITCHBOT,
            OperationOutcome.FAILED,
            elapsed_seconds=5,
            failure_category=FailureCategory.NETWORK,
        )
    )

    path = tmp_path / "state" / "sumicore" / "operational-metrics.jsonl"
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    record = json.loads(path.read_text())
    assert set(record) == {"date", "kind", "job", "outcome", "duration", "failure_category"}
    assert record["kind"] == "operation"
    assert record["job"] == "switchbot"
    assert record["date"].count("-") == 2
    assert "T" not in record["date"]
    assert "payload" not in record
    assert str(path) not in path.read_text()


def test_operational_journal_rotates_at_limit_and_keeps_two_generations(tmp_path) -> None:
    journal = OperationalMetricsJournal(tmp_path / "state")
    journal.maximum_bytes = 1
    metric = OperationMetric.from_result(
        OperationName.DAILY,
        OperationOutcome.COMPLETED,
        elapsed_seconds=0,
    )

    journal.append(metric)
    journal.append(metric)
    journal.append(metric)
    journal.append(metric)

    directory = tmp_path / "state" / "sumicore"
    assert (directory / "operational-metrics.jsonl").exists()
    assert (directory / "operational-metrics.jsonl.1").exists()
    assert (directory / "operational-metrics.jsonl.2").exists()
    assert not (directory / "operational-metrics.jsonl.3").exists()


def test_operational_journal_rejects_symlinked_file_or_directory(tmp_path) -> None:
    state_home = tmp_path / "state"
    journal = OperationalMetricsJournal(state_home)
    journal.path.parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_text("not a journal")
    journal.path.symlink_to(outside)

    with pytest.raises(RuntimeError, match="unsafe"):
        journal.append(
            OperationMetric.from_result(
                OperationName.DAILY_HEALTH,
                OperationOutcome.COMPLETED,
                elapsed_seconds=0,
            )
        )
    assert outside.read_text() == "not a journal"


def test_operational_journal_rejects_relative_state_home() -> None:
    with pytest.raises(ValueError, match="absolute"):
        OperationalMetricsJournal("relative-state")


def test_operational_journal_leaves_existing_state_home_mode_unchanged(tmp_path) -> None:
    state_home = tmp_path / "shared-state"
    state_home.mkdir(mode=0o755)
    state_home.chmod(0o755)
    journal = OperationalMetricsJournal(state_home)

    journal.append(
        OperationMetric.from_result(
            OperationName.DAILY_HEALTH,
            OperationOutcome.COMPLETED,
            elapsed_seconds=0,
        )
    )

    assert stat.S_IMODE(state_home.stat().st_mode) == 0o755
    assert stat.S_IMODE((state_home / "sumicore").stat().st_mode) == 0o700


def test_operational_journal_uses_absolute_path_override(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "separate" / "metrics.jsonl"
    monkeypatch.setenv("SUMICORE_OPERATIONAL_METRICS_PATH", str(destination))
    journal = OperationalMetricsJournal(tmp_path / "ignored")

    journal.append(
        OperationMetric.from_result(
            OperationName.DAILY,
            OperationOutcome.COMPLETED,
            elapsed_seconds=0,
        )
    )

    assert journal.path == destination
    assert destination.exists()


def test_custom_path_rotates_using_its_own_filename(tmp_path, monkeypatch) -> None:
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    destination = directory / "custom-metrics.jsonl"
    monkeypatch.setenv("SUMICORE_OPERATIONAL_METRICS_PATH", str(destination))
    journal = OperationalMetricsJournal()
    journal.maximum_bytes = 1
    metric = OperationMetric.from_result(
        OperationName.DAILY,
        OperationOutcome.COMPLETED,
        elapsed_seconds=0,
    )

    journal.append(metric)
    journal.append(metric)

    assert (directory / "custom-metrics.jsonl.1").exists()
    assert not (directory / "operational-metrics.jsonl.1").exists()


def test_custom_path_refuses_to_change_an_existing_shared_directory_mode(
    tmp_path, monkeypatch
) -> None:
    directory = tmp_path / "shared"
    directory.mkdir(mode=0o755)
    directory.chmod(0o755)
    monkeypatch.setenv(
        "SUMICORE_OPERATIONAL_METRICS_PATH", str(directory / "metrics.jsonl")
    )
    journal = OperationalMetricsJournal()

    with pytest.raises(RuntimeError, match="must be private"):
        journal.append(
            OperationMetric.from_result(
                OperationName.DAILY,
                OperationOutcome.COMPLETED,
                elapsed_seconds=0,
            )
        )
    assert stat.S_IMODE(directory.stat().st_mode) == 0o755
