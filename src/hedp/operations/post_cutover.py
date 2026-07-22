"""Evaluate a saved post-cutover status snapshot without live-system access."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO 8601 string")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def evaluate_post_cutover(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return pass/warn/fail findings for a caller-provided status snapshot."""
    started_at = _timestamp(snapshot.get("started_at"), "started_at")
    checked_at = _timestamp(snapshot.get("checked_at"), "checked_at")
    if checked_at < started_at:
        raise ValueError("checked_at must not precede started_at")
    findings: list[dict[str, str]] = []

    def add(level: str, check: str, message: str) -> None:
        findings.append({"level": level, "check": check, "message": message})

    elapsed_hours = (checked_at - started_at).total_seconds() / 3600
    if elapsed_hours < 24:
        add("warn", "observation_window", f"24時間観察の途中です（{elapsed_hours:.1f}時間）")
    else:
        add("pass", "observation_window", f"観察時間は{elapsed_hours:.1f}時間です")

    database = snapshot.get("database", {})
    if not isinstance(database, dict):
        raise ValueError("database must be an object")
    add(
        "pass" if database.get("integrity") == "ok" else "fail",
        "database_integrity",
        "DB整合性検査はokです" if database.get("integrity") == "ok" else "DB整合性検査がokではありません",
    )
    start_count = database.get("raw_count_start")
    end_count = database.get("raw_count_end")
    if not isinstance(start_count, int) or not isinstance(end_count, int):
        raise ValueError("database raw counts must be integers")
    if end_count < start_count:
        add("fail", "raw_count", "Raw件数が切替前より減少しています")
    elif end_count == start_count:
        add("warn", "raw_count", "Raw件数に増加がありません")
    else:
        add("pass", "raw_count", f"Raw件数は{end_count - start_count}件増加しました")

    safety = snapshot.get("safety", {})
    if not isinstance(safety, dict):
        raise ValueError("safety must be an object")
    checks = (
        ("old_jobs_running", "旧HEDPジョブが稼働しています"),
        ("duplicate_runs_detected", "二重実行を検出しました"),
        ("secrets_in_logs", "通常ログに秘密値を検出しました"),
        ("local_config_git_tracked", "家庭固有設定がGit管理対象です"),
    )
    for key, failure_message in checks:
        value = safety.get(key)
        if not isinstance(value, bool):
            raise ValueError(f"safety.{key} must be a boolean")
        add("fail" if value else "pass", key, failure_message if value else f"{key}は検出されていません")

    jobs = snapshot.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("jobs must be a non-empty array")
    for index, job in enumerate(jobs):
        if not isinstance(job, dict):
            raise ValueError(f"jobs[{index}] must be an object")
        name = job.get("name")
        expected = job.get("expected_runs")
        successes = job.get("successful_runs")
        failures = job.get("failed_runs")
        if not isinstance(name, str) or not name:
            raise ValueError(f"jobs[{index}].name must be a non-empty string")
        if not all(isinstance(value, int) and value >= 0 for value in (expected, successes, failures)):
            raise ValueError(f"job counts for {name} must be non-negative integers")
        if failures:
            add("fail", f"job:{name}", f"{name}で{failures}回の失敗があります")
        elif successes < expected:
            level = "warn" if elapsed_hours < 24 else "fail"
            add(level, f"job:{name}", f"{name}の成功回数が不足しています（{successes}/{expected}）")
        else:
            add("pass", f"job:{name}", f"{name}は{successes}/{expected}回成功しました")

    failed = sum(item["level"] == "fail" for item in findings)
    warned = sum(item["level"] == "warn" for item in findings)
    return {
        "status": "fail" if failed else "warn" if warned else "pass",
        "elapsed_hours": round(elapsed_hours, 2),
        "summary": {"pass": len(findings) - failed - warned, "warn": warned, "fail": failed},
        "findings": findings,
    }
