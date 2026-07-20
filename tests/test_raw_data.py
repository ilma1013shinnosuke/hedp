from datetime import datetime, timezone

from hedp.raw_data import RawData


def test_json_round_trip() -> None:
    raw_data = RawData(
        source="test-source",
        timestamp=datetime(2026, 7, 20, 12, 34, 56, tzinfo=timezone.utc),
        payload={"value": 42, "active": True, "label": "test"},
    )

    restored = RawData.from_json(raw_data.to_json())

    assert restored == raw_data
