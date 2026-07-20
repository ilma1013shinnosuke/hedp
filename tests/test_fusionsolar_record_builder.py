from copy import deepcopy
from datetime import datetime, timezone

from hedp.fusionsolar_record_builder import FusionSolarRecordBuilder
from hedp.raw_data import RawData
from hedp.record import Record


def test_build_creates_reproducible_records_without_changing_payload() -> None:
    payload = {
        "data": {
            "list": [
                {
                    "fmtCollectTimeStr": "2026-07-20 09:30:00",
                    "productPower": 1,
                    "inverterPower": 2.5,
                    "onGridPower": 3,
                    "buyPower": 4.5,
                    "powerProfit": 500,
                    "ignored": 999,
                }
            ]
        }
    }
    original_payload = deepcopy(payload)
    raw_data = RawData(
        source="fusionsolar",
        timestamp=datetime(2026, 7, 20, tzinfo=timezone.utc),
        payload=payload,
    )
    builder = FusionSolarRecordBuilder()
    timestamp = datetime(2026, 7, 20, 0, 30, tzinfo=timezone.utc)
    expected = [
        Record("fusionsolar", timestamp, "productPower", 1, "kW"),
        Record("fusionsolar", timestamp, "inverterPower", 2.5, "kW"),
        Record("fusionsolar", timestamp, "onGridPower", 3, "kW"),
        Record("fusionsolar", timestamp, "buyPower", 4.5, "kW"),
        Record("fusionsolar", timestamp, "powerProfit", 500, "JPY"),
    ]

    first = builder.build(raw_data)
    second = builder.build(raw_data)

    assert first == expected
    assert second == expected
    assert first == second
    assert payload == original_payload


def test_build_skips_missing_values() -> None:
    raw_data = RawData(
        source="fusionsolar",
        timestamp=datetime(2026, 7, 20, tzinfo=timezone.utc),
        payload={
            "data": {
                "list": [
                    {
                        "fmtCollectTimeStr": "2026-07-20 09:30:00",
                        "productPower": 1,
                    }
                ]
            }
        },
    )

    records = FusionSolarRecordBuilder().build(raw_data)

    assert [record.metric for record in records] == ["productPower"]
