from __future__ import annotations

import sqlite3

import pytest

from hedp.operations.operational_metrics import (
    FailureCategory,
    OperationMetric,
    OperationName,
    OperationOutcome,
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
        OperationName.COLLECTION,
        OperationOutcome.SKIPPED,
        elapsed_seconds=0.2,
        failure_category=FailureCategory.LOCK_HELD,
    )

    assert metric.to_dict() == {
        "operation": "collection",
        "outcome": "skipped",
        "duration": "under_1s",
        "failure_category": "lock_held",
    }


def test_operation_metric_rejects_ambiguous_outcomes() -> None:
    with pytest.raises(ValueError, match="require a failure category"):
        OperationMetric.from_result(
            OperationName.COLLECTION, OperationOutcome.FAILED, 1
        )
    with pytest.raises(ValueError, match="require the timeout category"):
        OperationMetric.from_result(
            OperationName.COLLECTION,
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
        "status": "unavailable",
        "database_bytes": 0,
        "filesystem_free_bytes": 0,
        "page_count": None,
        "free_page_count": None,
        "raw_data_rows": None,
        "record_rows": None,
        "probe_duration": "under_1s",
    }
