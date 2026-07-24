from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hedp.adapters.switchbot.storage import SwitchBotStorage
from hedp.storage import RawData, Record, Storage
from scripts.archive_switchbot_observations import create_month_archive
from scripts.build_compact_database import build_compact_database


def observation(timestamp: str, value: float) -> dict[str, object]:
    return {
        "device_id": "fixture-device",
        "observed_at_utc": timestamp,
        "observed_at_local": timestamp,
        "timezone": "UTC",
        "observation_kind": "status_snapshot",
        "temperature_c": value,
        "source": "switchbot_csv_export",
        "source_precision": "second",
        "collection_method": "csv_import",
        "measurement_status": "observed",
        "raw_payload_json": f'{{"temperature":{value}}}',
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def source_database(tmp_path: Path) -> Path:
    path = tmp_path / "source.db"
    common = Storage(str(path))
    common_connection = common.connect()
    raw = RawData(
        source="fixture",
        timestamp=datetime(2026, 7, 1, tzinfo=timezone.utc),
        payload={"value": 1},
    )
    common.save_rawdata(raw)
    common.save_records(
        [
            Record(
                source="fixture",
                timestamp=raw.timestamp,
                metric="value",
                value=1,
                unit="count",
            )
        ]
    )
    common_connection.close()

    switchbot = SwitchBotStorage(str(path))
    switchbot.connect()
    switchbot.insert_observation(
        observation("2026-06-30T23:59:59+00:00", 19.0)
    )
    switchbot.insert_observation(
        observation("2026-07-01T00:00:00+00:00", 20.0)
    )
    switchbot.insert_observation(
        observation("2026-07-31T23:59:59+00:00", 21.0)
    )
    switchbot.insert_observation(
        observation("2026-08-01T00:00:00+00:00", 22.0)
    )
    switchbot.commit()
    switchbot.close()
    return path


def test_build_compact_database_keeps_source_and_excludes_archived_rows(
    tmp_path: Path,
) -> None:
    source = source_database(tmp_path)
    archive = tmp_path / "2026-07.archive"
    create_month_archive(source, archive, month="2026-07")
    source_before = source.read_bytes()
    destination = tmp_path / "compact.db"

    report = build_compact_database(source, destination, [archive])

    assert source.read_bytes() == source_before
    assert report["integrity"] == "ok"
    assert report["source_observations"] == 4
    assert report["archived_observations"] == 2
    assert report["compact_observations"] == 2
    connection = sqlite3.connect(destination)
    try:
        rows = connection.execute(
            "SELECT observed_at_utc FROM switchbot_observations "
            "ORDER BY observed_at_utc"
        ).fetchall()
        assert rows == [
            ("2026-06-30T23:59:59+00:00",),
            ("2026-08-01T00:00:00+00:00",),
        ]
        assert connection.execute("SELECT count(*) FROM raw_data").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM records").fetchone()[0] == 1
    finally:
        connection.close()
    compact = Storage(str(destination))
    compact_connection = compact.connect()
    try:
        previous_max = compact_connection.execute(
            "SELECT max(id) FROM raw_data"
        ).fetchone()[0]
        compact.save_rawdata(
            RawData(
                source="fixture-next",
                timestamp=datetime(2026, 8, 1, tzinfo=timezone.utc),
                payload={"value": 2},
            )
        )
        current_max = compact_connection.execute(
            "SELECT max(id) FROM raw_data"
        ).fetchone()[0]
        assert current_max > previous_max
    finally:
        compact_connection.close()


def test_build_refuses_archive_that_no_longer_matches_source(
    tmp_path: Path,
) -> None:
    source = source_database(tmp_path)
    archive = tmp_path / "2026-07.archive"
    create_month_archive(source, archive, month="2026-07")
    connection = sqlite3.connect(source)
    connection.execute(
        "UPDATE switchbot_observations SET temperature_c=99 "
        "WHERE observed_at_utc='2026-07-01T00:00:00+00:00'"
    )
    connection.commit()
    connection.close()

    with pytest.raises(Exception, match="source records"):
        build_compact_database(
            source,
            tmp_path / "compact.db",
            [archive],
        )
    assert not (tmp_path / "compact.db").exists()


def test_build_refuses_unknown_source_table(tmp_path: Path) -> None:
    source = source_database(tmp_path)
    archive = tmp_path / "2026-07.archive"
    create_month_archive(source, archive, month="2026-07")
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE future_data (id INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()

    with pytest.raises(Exception, match="table set"):
        build_compact_database(
            source,
            tmp_path / "compact.db",
            [archive],
        )
