from __future__ import annotations

import json
import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
import os

import pytest

from hedp.operations.operational_metrics import (
    FailureCategory,
    OperationMetric,
    OperationName,
    OperationOutcome,
    OperatorActivity,
    OperatorMetric,
    OperationalMetricsJournal,
    ReadOnlyDatabaseMetrics,
    duration_bucket,
    summarize_operational_metrics,
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


def test_operator_metric_records_only_fixed_activity_count_and_coarse_time() -> None:
    metric = OperatorMetric.from_observation(
        OperatorActivity.MANUAL_RECOVERY,
        count=2,
        elapsed_seconds=45,
    )

    assert metric.to_dict() == {
        "activity": "manual_recovery",
        "count": 2,
        "duration": "30s_or_more",
    }
    with pytest.raises(ValueError, match="between 1 and 1000"):
        OperatorMetric.from_observation(
            OperatorActivity.WARNING_REVIEW,
            count=0,
            elapsed_seconds=1,
        )


def test_readonly_database_metrics_avoids_table_scans_by_default(tmp_path) -> None:
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
    assert report["raw_data_rows"] is None
    assert report["record_rows"] is None
    assert "observations.db" not in repr(report)
    assert "private" not in repr(report)
    with sqlite3.connect(database) as verify:
        assert verify.execute("SELECT data FROM raw_data").fetchone()[0] == "private payload"


def test_readonly_database_metrics_counts_rows_only_when_explicitly_requested(
    tmp_path,
) -> None:
    database = tmp_path / "observations.db"
    storage = Storage(str(database))
    connection = storage.connect()
    connection.execute("INSERT INTO raw_data (data) VALUES ('private payload')")
    connection.execute("INSERT INTO records (data) VALUES ('private record')")
    connection.commit()
    connection.close()

    report = ReadOnlyDatabaseMetrics().collect(
        database, include_table_counts=True
    ).to_dict()

    assert report["raw_data_rows"] == 1
    assert report["record_rows"] == 1
    assert "private" not in repr(report)


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


def test_operational_journal_serialises_concurrent_appends_without_losing_records(tmp_path) -> None:
    journal = OperationalMetricsJournal(tmp_path / "state")
    metric = OperationMetric.from_result(
        OperationName.DAILY,
        OperationOutcome.COMPLETED,
        elapsed_seconds=0,
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(journal.append, metric) for _ in range(24)]
        for future in futures:
            future.result()

    records = [json.loads(line) for line in journal.path.read_text().splitlines()]
    assert len(records) == 24
    assert all(record["job"] == "daily" for record in records)
    assert not journal._lock_path.exists()


def test_operational_journal_serialises_rotation_during_concurrent_appends(tmp_path) -> None:
    journal = OperationalMetricsJournal(tmp_path / "state")
    journal.maximum_bytes = 1
    metric = OperationMetric.from_result(
        OperationName.DAILY,
        OperationOutcome.COMPLETED,
        elapsed_seconds=0,
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(journal.append, metric) for _ in range(16)]
        for future in futures:
            future.result()

    paths = [journal.path, journal._generation_path(1), journal._generation_path(2)]
    records = []
    for path in paths:
        assert path.exists()
        assert stat.S_ISREG(os.lstat(path).st_mode)
        records.extend(json.loads(line) for line in path.read_text().splitlines())
    assert 1 <= len(records) <= 3
    assert all(record["job"] == "daily" for record in records)
    assert not journal._lock_path.exists()


def test_busy_journal_does_not_modify_existing_record_when_recorder_fails(tmp_path) -> None:
    journal = OperationalMetricsJournal(tmp_path / "state")
    metric = OperationMetric.from_result(
        OperationName.DAILY,
        OperationOutcome.COMPLETED,
        elapsed_seconds=0,
    )
    journal.append(metric)
    before = journal.path.read_bytes()
    journal._lock_path.mkdir()
    (journal._lock_path / journal._lock_owner_filename).write_text(
        json.dumps({"pid": os.getpid(), "created_at": 0})
    )
    journal.lock_wait_seconds = 0

    with pytest.raises(RuntimeError, match="busy"):
        journal.append(metric)

    assert journal.path.read_bytes() == before


def test_operational_journal_recovers_only_a_stale_lock_with_dead_owner(
    tmp_path, monkeypatch
) -> None:
    journal = OperationalMetricsJournal(tmp_path / "state")
    journal._prepare_directory()
    journal._lock_path.mkdir()
    (journal._lock_path / journal._lock_owner_filename).write_text(
        json.dumps({"pid": 12345, "created_at": 0})
    )
    os.utime(journal._lock_path, (0, 0))
    monkeypatch.setattr(journal, "_owner_process_is_alive", lambda _pid: False)

    journal.append(
        OperationMetric.from_result(
            OperationName.DAILY,
            OperationOutcome.COMPLETED,
            elapsed_seconds=0,
        )
    )

    assert journal.path.exists()
    assert not journal._lock_path.exists()
    assert not list(journal.path.parent.glob(".*.stale-*"))


def test_operational_journal_recovers_an_empty_stale_lock_after_creator_crash(tmp_path) -> None:
    journal = OperationalMetricsJournal(tmp_path / "state")
    journal._prepare_directory()
    journal._lock_path.mkdir()
    os.utime(journal._lock_path, (0, 0))

    journal.append(
        OperationMetric.from_result(
            OperationName.DAILY,
            OperationOutcome.COMPLETED,
            elapsed_seconds=0,
        )
    )

    assert journal.path.exists()
    assert not journal._lock_path.exists()
    assert not list(journal.path.parent.glob(".*.stale-*"))


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


def test_summary_reads_current_and_two_generations_with_strict_schema(tmp_path) -> None:
    journal = OperationalMetricsJournal(tmp_path / "state")
    journal.maximum_bytes = 1
    journal.append(
        OperationMetric.from_result(
            OperationName.SWITCHBOT,
            OperationOutcome.FAILED,
            elapsed_seconds=1,
            failure_category=FailureCategory.NETWORK,
        )
    )
    journal.append(
        OperationMetric.from_result(
            OperationName.SWITCHBOT,
            OperationOutcome.SKIPPED,
            elapsed_seconds=0,
            failure_category=FailureCategory.LOCK_HELD,
        )
    )
    journal.append(
        OperationMetric.from_result(
            OperationName.DAILY,
            OperationOutcome.COMPLETED,
            elapsed_seconds=5,
        )
    )
    journal.path.write_text('{"date":"2026-07-25","kind":"operation","payload":"secret"}\nnot json\n')

    summary = summarize_operational_metrics(tmp_path / "state")

    assert summary["files_read"] == 3
    assert summary["accepted_records"] == 2
    assert summary["invalid_lines"] == 2
    assert summary["operation_counts"] == [
        {
            "date": summary["operation_counts"][0]["date"],
            "job": "switchbot",
            "outcome": "failed",
            "failure_category": "network",
            "duration": "1_to_5s",
            "count": 1,
        },
        {
            "date": summary["operation_counts"][1]["date"],
            "job": "switchbot",
            "outcome": "skipped",
            "failure_category": "lock_held",
            "duration": "under_1s",
            "count": 1,
        },
    ]
    assert "secret" not in repr(summary)


def test_summary_reports_database_growth_without_paths_or_payloads(tmp_path) -> None:
    journal = OperationalMetricsJournal(tmp_path / "state")
    journal.append(
        ReadOnlyDatabaseMetrics().collect(tmp_path / "missing.db", job=OperationName.DAILY)
    )
    path = journal.path
    path.write_text(
        "\n".join(
            [
                json.dumps({
                    "date": "2026-07-20", "kind": "database", "job": "daily", "status": "ok",
                    "database_bytes": 100, "filesystem_free_bytes": 900, "page_count": 1,
                    "free_page_count": 0, "raw_data_rows": 2, "record_rows": 3, "probe_duration": "under_1s",
                }),
                json.dumps({
                    "date": "2026-07-22", "kind": "database", "job": "daily", "status": "ok",
                    "database_bytes": 160, "filesystem_free_bytes": 840, "page_count": 2,
                    "free_page_count": 0, "raw_data_rows": 4, "record_rows": 6, "probe_duration": "under_1s",
                }),
            ]
        ) + "\n"
    )

    summary = summarize_operational_metrics(tmp_path / "state")

    assert summary["database_capacity"] == {
        "observed_days": 2,
        "first_database_bytes": 100,
        "last_database_bytes": 160,
        "database_bytes_delta": 60,
    }
    assert "missing.db" not in repr(summary)


def test_summary_counts_warning_review_and_manual_recovery_effort(tmp_path) -> None:
    journal = OperationalMetricsJournal(tmp_path / "state")
    journal.append(
        OperatorMetric.from_observation(
            OperatorActivity.WARNING_REVIEW, count=3, elapsed_seconds=12
        )
    )
    journal.append(
        OperatorMetric.from_observation(
            OperatorActivity.MANUAL_RECOVERY, count=1, elapsed_seconds=40
        )
    )

    summary = summarize_operational_metrics(tmp_path / "state")

    assert summary["operator_counts"] == [
        {
            "date": summary["operator_counts"][0]["date"],
            "activity": "manual_recovery",
            "duration": "30s_or_more",
            "count": 1,
        },
        {
            "date": summary["operator_counts"][1]["date"],
            "activity": "warning_review",
            "duration": "5_to_30s",
            "count": 3,
        },
    ]


def test_summary_rejects_boolean_numbers_and_unknown_vocabulary(tmp_path) -> None:
    journal = OperationalMetricsJournal(tmp_path / "state")
    journal.path.parent.mkdir(parents=True, mode=0o700)
    journal.path.write_text(
        "\n".join(
            [
                json.dumps({
                    "date": "2026-07-25", "kind": "database", "job": "daily", "status": "ok",
                    "database_bytes": True, "filesystem_free_bytes": 10, "page_count": 1,
                    "free_page_count": 0, "raw_data_rows": 1, "record_rows": 1, "probe_duration": "under_1s",
                }),
                json.dumps({
                    "date": "2026-07-25", "kind": "operation", "job": "unknown", "outcome": "failed",
                    "duration": "under_1s", "failure_category": "internal",
                }),
                json.dumps({
                    "date": "2026-7-5", "kind": "operation", "job": "daily", "outcome": "failed",
                    "duration": "under_1s", "failure_category": "internal",
                }),
            ]
        ) + "\n"
    )

    summary = summarize_operational_metrics(tmp_path / "state")

    assert summary["accepted_records"] == 0
    assert summary["invalid_lines"] == 3
    assert summary["database_capacity"]["database_bytes_delta"] is None
