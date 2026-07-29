#!/usr/bin/env python3
"""Summarize a bounded Modbus read-only window without returning payloads."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sqlite3


SOURCE = "fusionsolar_modbus_tcp"


def summarize_window(
    database: Path,
    *,
    started_at: datetime,
    ended_at: datetime,
) -> dict[str, object]:
    if started_at.tzinfo is None or ended_at.tzinfo is None:
        raise ValueError("window timestamps must include a UTC offset")
    if ended_at <= started_at:
        raise ValueError("window end must be after start")
    resolved = database.resolve()
    connection = sqlite3.connect(
        f"{resolved.as_uri()}?mode=ro",
        uri=True,
        timeout=1,
    )
    try:
        connection.execute("PRAGMA query_only = ON")
        values = [
            datetime.fromisoformat(str(row[0]))
            for row in connection.execute(
                "SELECT json_extract(data, '$.timestamp') "
                "FROM raw_data "
                "WHERE json_extract(data, '$.source') = ? "
                "AND json_extract(data, '$.timestamp') >= ? "
                "AND json_extract(data, '$.timestamp') <= ? "
                "ORDER BY json_extract(data, '$.timestamp')",
                (SOURCE, started_at.isoformat(), ended_at.isoformat()),
            )
            if row[0]
        ]
    finally:
        connection.close()
    gaps = [
        (current - previous).total_seconds()
        for previous, current in zip(values, values[1:])
    ]
    return {
        "schema_version": 1,
        "source": "approved_modbus_read_only",
        "window": {
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
        },
        "sample_count": len(values),
        "max_gap_seconds": round(max(gaps), 3) if gaps else None,
        "gaps_over_15_minutes": sum(gap > 900 for gap in gaps),
        "status": (
            "pass"
            if values and not any(gap > 900 for gap in gaps)
            else "review"
        ),
    }


def _aware_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a UTC offset")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--started-at", type=_aware_timestamp, required=True)
    parser.add_argument("--ended-at", type=_aware_timestamp, required=True)
    arguments = parser.parse_args(argv)
    try:
        report = summarize_window(
            arguments.database,
            started_at=arguments.started_at,
            ended_at=arguments.ended_at,
        )
    except Exception:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "unavailable",
                    "reason": "window_summary_failed",
                },
                separators=(",", ":"),
            )
        )
        return 1
    print(json.dumps(report, separators=(",", ":"), sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
