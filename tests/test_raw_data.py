from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone

import pytest

from hedp.storage import RawData


def test_json_round_trip() -> None:
    raw_data = RawData(
        source="test-source",
        timestamp=datetime(2026, 7, 20, 12, 34, 56, tzinfo=timezone.utc),
        payload={"value": 42, "active": True, "label": "test"},
        target_date=date(2026, 7, 20),
    )

    restored = RawData.from_json(raw_data.to_json())

    assert restored == raw_data


def test_from_json_accepts_old_json_without_target_date() -> None:
    raw_data = RawData.from_json(
        '{"source":"test-source","timestamp":"2026-07-20T00:00:00+00:00",'
        '"payload":{"value":42}}'
    )

    assert raw_data.target_date is None


def test_source_cannot_be_changed() -> None:
    raw_data = RawData(
        source="test-source",
        timestamp=datetime(2026, 7, 20, 12, 34, 56, tzinfo=timezone.utc),
        payload={"value": 42},
    )

    with pytest.raises(FrozenInstanceError):
        raw_data.source = "changed-source"
