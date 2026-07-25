#!/usr/bin/env python3
"""Append one anonymous, date-only operational metric without exposing secrets."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPOSITORY_SOURCE = Path(__file__).resolve().parents[1] / "src"
if str(REPOSITORY_SOURCE) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_SOURCE))

from hedp.configuration import Configuration
from hedp.operations.operational_metrics import (
    FailureCategory,
    OperationMetric,
    OperationName,
    OperationOutcome,
    OperationalMetricsJournal,
    ReadOnlyDatabaseMetrics,
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    command = value.add_subparsers(dest="command", required=True)
    operation = command.add_parser("operation")
    operation.add_argument("job", choices=[item.value for item in OperationName])
    operation.add_argument("outcome", choices=[item.value for item in OperationOutcome])
    operation.add_argument("elapsed_seconds", type=float)
    operation.add_argument(
        "failure_category", choices=[item.value for item in FailureCategory]
    )
    command.add_parser("database")
    return value


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = parser().parse_args(argv)
        journal = OperationalMetricsJournal()
        if arguments.command == "operation":
            metric = OperationMetric.from_result(
                OperationName(arguments.job),
                OperationOutcome(arguments.outcome),
                arguments.elapsed_seconds,
                FailureCategory(arguments.failure_category),
            )
        else:
            metric = ReadOnlyDatabaseMetrics().collect(
                Configuration.database_path_from_environment(), job=OperationName.DAILY
            )
        journal.append(metric)
    except Exception:
        print("unable to record operational metric", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
