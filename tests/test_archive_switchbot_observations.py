from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from hedp.adapters.switchbot.storage import SwitchBotStorage
from hedp.storage.jsonl_archive import (
    iter_jsonl_gzip_archive,
    verify_jsonl_gzip_archive,
)
from scripts.archive_switchbot_observations import (
    create_month_archive,
    inspect_month,
    month_bounds,
)


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


def database(tmp_path: Path) -> Path:
    path = tmp_path / "source.db"
    storage = SwitchBotStorage(str(path))
    storage.connect()
    storage.insert_observation(
        observation("2026-06-30T23:59:59+00:00", 19.0)
    )
    storage.insert_observation(
        observation("2026-07-01T00:00:00+00:00", 20.0)
    )
    storage.insert_observation(
        observation("2026-07-31T23:59:59+00:00", 21.0)
    )
    storage.insert_observation(
        observation("2026-08-01T00:00:00+00:00", 22.0)
    )
    storage.commit()
    storage.close()
    return path


def test_month_bounds_handle_year_end() -> None:
    assert month_bounds("2026-12") == (
        "2026-12-01T00:00:00+00:00",
        "2027-01-01T00:00:00+00:00",
    )


def test_month_bounds_reject_invalid_value() -> None:
    with pytest.raises(ValueError, match="YYYY-MM"):
        month_bounds("2026-13")


def test_inspect_and_archive_one_month_without_changing_database(
    tmp_path: Path,
) -> None:
    source = database(tmp_path)
    before = source.read_bytes()
    storage = SwitchBotStorage(str(source))
    connection = storage.connect_readonly()
    try:
        report = inspect_month(
            connection,
            month="2026-07",
            source="switchbot_csv_export",
        )
    finally:
        storage.close()

    assert report["record_count"] == 2
    destination = tmp_path / "2026-07.archive"
    manifest = create_month_archive(source, destination, month="2026-07")

    assert manifest["record_count"] == 2
    assert verify_jsonl_gzip_archive(destination) == manifest
    rows = list(iter_jsonl_gzip_archive(destination))
    assert [row["temperature_c"] for row in rows] == [20.0, 21.0]
    assert source.read_bytes() == before


def test_archive_rejects_empty_month(tmp_path: Path) -> None:
    source = database(tmp_path)

    with pytest.raises(ValueError, match="no observations"):
        create_month_archive(
            source,
            tmp_path / "2025-01.archive",
            month="2025-01",
        )
