from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

import pytest

from scripts.summarize_modbus_read_only_window import summarize_window


START = datetime(2026, 7, 30, tzinfo=timezone.utc)


def _database(path: Path, offsets: tuple[int, ...]) -> Path:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE raw_data (data TEXT NOT NULL)")
        for offset in offsets:
            connection.execute(
                "INSERT INTO raw_data (data) VALUES (?)",
                (
                    json.dumps(
                        {
                            "source": "fusionsolar_modbus_tcp",
                            "timestamp": (
                                START + timedelta(seconds=offset)
                            ).isoformat(),
                            "payload": {"private": "not-read"},
                        }
                    ),
                ),
            )
        connection.execute(
            "INSERT INTO raw_data (data) VALUES (?)",
            (
                json.dumps(
                    {
                        "source": "other",
                        "timestamp": START.isoformat(),
                        "payload": {"private": "ignored"},
                    }
                ),
            ),
        )
    return path


def test_window_summary_counts_only_modbus_and_never_returns_payload(tmp_path) -> None:
    database = _database(tmp_path / "fixture.sqlite3", (0, 300, 605))

    report = summarize_window(
        database,
        started_at=START,
        ended_at=START + timedelta(minutes=15),
    )

    assert report["sample_count"] == 3
    assert report["max_gap_seconds"] == 305
    assert report["gaps_over_15_minutes"] == 0
    assert report["status"] == "pass"
    assert "private" not in repr(report)
    assert str(database) not in repr(report)


def test_window_summary_marks_long_gap_for_review(tmp_path) -> None:
    database = _database(tmp_path / "fixture.sqlite3", (0, 901))

    report = summarize_window(
        database,
        started_at=START,
        ended_at=START + timedelta(minutes=20),
    )

    assert report["gaps_over_15_minutes"] == 1
    assert report["status"] == "review"


def test_window_summary_rejects_invalid_window_without_opening_database(
    tmp_path,
) -> None:
    with pytest.raises(ValueError, match="after start"):
        summarize_window(
            tmp_path / "missing.sqlite3",
            started_at=START,
            ended_at=START,
        )
