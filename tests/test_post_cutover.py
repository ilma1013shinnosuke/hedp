from copy import deepcopy

import pytest

from hedp.operations.post_cutover import create_post_cutover_snapshot, evaluate_post_cutover


@pytest.fixture
def healthy_snapshot() -> dict[str, object]:
    return {
        "started_at": "2026-07-21T10:00:00+09:00",
        "checked_at": "2026-07-22T10:01:00+09:00",
        "database": {"integrity": "ok", "raw_count_start": 100, "raw_count_end": 450},
        "safety": {"old_jobs_running": False, "duplicate_runs_detected": False, "secrets_in_logs": False, "local_config_git_tracked": False},
        "jobs": [{"name": "device-realtime", "expected_runs": 288, "successful_runs": 288, "failed_runs": 0}],
    }


def test_healthy_snapshot_passes(healthy_snapshot: dict[str, object]) -> None:
    assert evaluate_post_cutover(healthy_snapshot)["status"] == "pass"


def test_incomplete_window_and_missing_runs_warn(healthy_snapshot: dict[str, object]) -> None:
    snapshot = deepcopy(healthy_snapshot)
    snapshot["checked_at"] = "2026-07-21T16:00:00+09:00"
    snapshot["jobs"][0]["successful_runs"] = 70
    result = evaluate_post_cutover(snapshot)
    assert result["status"] == "warn"
    assert result["summary"]["warn"] == 2


def test_safety_or_collection_failure_fails(healthy_snapshot: dict[str, object]) -> None:
    snapshot = deepcopy(healthy_snapshot)
    snapshot["safety"]["old_jobs_running"] = True
    snapshot["jobs"][0]["failed_runs"] = 1
    assert evaluate_post_cutover(snapshot)["summary"]["fail"] == 2


def test_naive_timestamp_is_rejected(healthy_snapshot: dict[str, object]) -> None:
    snapshot = deepcopy(healthy_snapshot)
    snapshot["checked_at"] = "2026-07-22T10:01:00"
    with pytest.raises(ValueError, match="timezone"):
        evaluate_post_cutover(snapshot)


def test_snapshot_builder_validates_redacted_facts():
    snapshot = create_post_cutover_snapshot(
        started_at="2026-07-21T10:00:00+09:00",
        checked_at="2026-07-22T10:00:00+09:00",
        integrity="ok", raw_count_start=10, raw_count_end=12,
        old_jobs_running=False, duplicate_runs_detected=False,
        secrets_in_logs=False, local_config_git_tracked=False,
        jobs=[{"name": "daily", "expected_runs": 1,
               "successful_runs": 1, "failed_runs": 0}],
    )
    assert snapshot["database"]["raw_count_end"] == 12
    assert evaluate_post_cutover(snapshot)["status"] == "pass"
