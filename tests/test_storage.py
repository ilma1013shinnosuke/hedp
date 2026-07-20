from datetime import datetime, timezone

from hedp.raw_data import RawData
from hedp.record import Record
from hedp.storage import Storage


def test_save_and_load_rawdata(tmp_path) -> None:
    storage = Storage(str(tmp_path / "test.db"))
    connection = storage.connect()
    raw_data = RawData(
        source="test-source",
        timestamp=datetime(2026, 7, 20, 12, 34, 56, tzinfo=timezone.utc),
        payload={"value": 42},
    )

    try:
        storage.save_rawdata(raw_data)

        assert storage.load_rawdata() == [raw_data]
    finally:
        connection.close()


def test_save_and_load_records(tmp_path) -> None:
    storage = Storage(str(tmp_path / "test.db"))
    connection = storage.connect()
    records = [
        Record(
            source="fusionsolar",
            timestamp=datetime(2026, 7, 20, tzinfo=timezone.utc),
            metric="productPower",
            value=42.5,
            unit="kW",
        )
    ]

    try:
        storage.save_records(records)

        assert storage.load_records() == records
    finally:
        connection.close()
