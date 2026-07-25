from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "source",
        "status",
        "retention_class",
        "data_kind",
        "contains_household_identifiers",
        "contains_sensitive_behavior",
        "max_payload_bytes",
        "max_events_per_day",
        "estimated_daily_bytes",
        "active_detail_days",
        "long_term_granularity",
        "long_term_retention_days",
        "archive_unit",
        "compression",
        "restore_procedure",
        "deletion_conditions",
    }
)
APPROVED_REQUIRED_VALUES = frozenset(
    {
        "max_payload_bytes",
        "max_events_per_day",
        "estimated_daily_bytes",
        "active_detail_days",
        "long_term_granularity",
        "long_term_retention_days",
        "archive_unit",
        "compression",
        "restore_procedure",
    }
)
DELETION_CONDITIONS = frozenset(
    {
        "archive_verified",
        "offsite_copy_verified",
        "source_not_in_active_use",
        "explicit_approval",
    }
)


def validate_retention_dictionary(value: object) -> tuple[str, ...]:
    if not isinstance(value, dict):
        return ("dictionary must be an object",)
    issues: list[str] = []
    missing = sorted(REQUIRED_FIELDS - value.keys())
    unknown = sorted(value.keys() - REQUIRED_FIELDS)
    if missing:
        issues.append(f"missing fields: {', '.join(missing)}")
    if unknown:
        issues.append(f"unknown fields: {', '.join(unknown)}")
    if value.get("schema_version") != 1:
        issues.append("schema_version must be 1")
    if not isinstance(value.get("source"), str) or not value.get("source"):
        issues.append("source must be a non-empty string")
    if value.get("status") not in {"draft", "approved"}:
        issues.append("status must be draft or approved")
    if value.get("retention_class") not in {"A", "B", "C", "D"}:
        issues.append("retention_class must be A, B, C, or D")
    if value.get("data_kind") not in {
        "raw",
        "continuous",
        "event",
        "audit",
        "current",
        "state_interval",
        "observation_coverage",
    }:
        issues.append("data_kind is invalid")
    for field in (
        "contains_household_identifiers",
        "contains_sensitive_behavior",
    ):
        if not isinstance(value.get(field), bool):
            issues.append(f"{field} must be a boolean")
    for field, minimum in (
        ("max_payload_bytes", 1),
        ("max_events_per_day", 1),
        ("estimated_daily_bytes", 0),
        ("active_detail_days", 1),
        ("long_term_retention_days", 1),
    ):
        item = value.get(field)
        if item is not None and (
            isinstance(item, bool)
            or not isinstance(item, int)
            or item < minimum
        ):
            issues.append(f"{field} must be null or an integer >= {minimum}")
    if value.get("archive_unit") not in {
        None,
        "day",
        "month",
        "source_schema_month",
        "none",
    }:
        issues.append("archive_unit is invalid")
    if value.get("compression") not in {None, "gzip", "none"}:
        issues.append("compression is invalid")
    for field in ("long_term_granularity", "restore_procedure"):
        item = value.get(field)
        if item is not None and (not isinstance(item, str) or not item):
            issues.append(f"{field} must be null or a non-empty string")
    conditions = value.get("deletion_conditions")
    if not isinstance(conditions, list) or any(
        item not in DELETION_CONDITIONS for item in conditions
    ):
        issues.append("deletion_conditions contains an invalid value")
    elif set(conditions) != DELETION_CONDITIONS:
        issues.append("deletion_conditions must contain every deletion gate")
    if value.get("status") == "approved":
        unresolved = sorted(
            field
            for field in APPROVED_REQUIRED_VALUES
            if value.get(field) is None
        )
        if unresolved:
            issues.append(
                "approved dictionary has unresolved fields: "
                + ", ".join(unresolved)
            )
    return tuple(issues)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    arguments = parser.parse_args(argv)
    try:
        value: Any = json.loads(
            arguments.path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        print(f"invalid: {type(error).__name__}")
        return 2
    issues = validate_retention_dictionary(value)
    if issues:
        for issue in issues:
            print(f"invalid: {issue}")
        return 1
    print("valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
