from datetime import date, datetime, timezone
import sqlite3

from hedp.raw_data import RawData
from hedp.record import Record
from hedp.storage import Storage


def test_backup_copies_data_creates_parent_overwrites_and_preserves_source(
    tmp_path,
) -> None:
    storage = Storage(str(tmp_path / "test.db"))
    connection = storage.connect()
    raw_data = RawData(
        source="test-source",
        timestamp=datetime(2026, 7, 20, tzinfo=timezone.utc),
        payload={"value": 42},
    )
    record = Record(
        source="test-source",
        timestamp=datetime(2026, 7, 20, tzinfo=timezone.utc),
        metric="power",
        value=42,
        unit="kW",
    )
    destination = tmp_path / "new" / "backups" / "backup.db"

    try:
        storage.save_rawdata(raw_data)
        storage.save_records([record])
        storage.backup(str(destination))

        with sqlite3.connect(destination) as backup_connection:
            backup_connection.execute(
                "INSERT INTO raw_data (data) VALUES ('obsolete')"
            )
        storage.backup(str(destination))

        with sqlite3.connect(destination) as backup_connection:
            raw_data_count = backup_connection.execute(
                "SELECT COUNT(*) FROM raw_data"
            ).fetchone()[0]
            record_count = backup_connection.execute(
                "SELECT COUNT(*) FROM records"
            ).fetchone()[0]

        assert destination.is_file()
        assert raw_data_count == 1
        assert record_count == 1
        assert storage.load_rawdata() == [raw_data]
        assert storage.load_records() == [record]
    finally:
        connection.close()


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


def test_load_records_for_range_filters_timezone_source_and_sorts(
    tmp_path,
) -> None:
    storage = Storage(str(tmp_path / "test.db"))
    connection = storage.connect()
    records = [
        Record(
            "fusionsolar",
            datetime(2026, 7, 19, 15, 5, tzinfo=timezone.utc),
            "productPower",
            1,
            "kW",
        ),
        Record(
            "fusionsolar",
            datetime(2026, 7, 19, 15, tzinfo=timezone.utc),
            "powerProfit",
            2,
            "JPY",
        ),
        Record(
            "fusionsolar",
            datetime(2026, 7, 19, 15, tzinfo=timezone.utc),
            "buyPower",
            3,
            "kW",
        ),
        Record(
            "other",
            datetime(2026, 7, 19, 15, tzinfo=timezone.utc),
            "productPower",
            4,
            "kW",
        ),
        Record(
            "fusionsolar",
            datetime(2026, 7, 20, 15, tzinfo=timezone.utc),
            "productPower",
            5,
            "kW",
        ),
    ]

    try:
        storage.save_records(records)

        assert storage.load_records_for_range(
            "fusionsolar", date(2026, 7, 20), date(2026, 7, 20)
        ) == [records[2], records[1], records[0]]
    finally:
        connection.close()


def test_save_rawdata_ignores_same_source_and_payload(tmp_path) -> None:
    storage = Storage(str(tmp_path / "test.db"))
    connection = storage.connect()
    raw_data = RawData(
        source="fusionsolar",
        timestamp=datetime(2026, 7, 20, tzinfo=timezone.utc),
        payload={"value": 42},
        target_date=date(2026, 7, 20),
    )
    later_raw_data = RawData(
        source="fusionsolar",
        timestamp=datetime(2026, 7, 21, tzinfo=timezone.utc),
        payload={"value": 42},
        target_date=date(2026, 7, 20),
    )
    different_target_date = RawData(
        source="fusionsolar",
        timestamp=datetime(2026, 7, 21, tzinfo=timezone.utc),
        payload={"value": 42},
        target_date=date(2026, 7, 21),
    )
    different_source = RawData(
        source="other",
        timestamp=datetime(2026, 7, 21, tzinfo=timezone.utc),
        payload={"value": 42},
        target_date=date(2026, 7, 20),
    )
    different_payload = RawData(
        source="fusionsolar",
        timestamp=datetime(2026, 7, 21, tzinfo=timezone.utc),
        payload={"value": 43},
        target_date=date(2026, 7, 20),
    )

    try:
        storage.save_rawdata(raw_data)
        storage.save_rawdata(later_raw_data)
        storage.save_rawdata(different_target_date)
        storage.save_rawdata(different_source)
        storage.save_rawdata(different_payload)

        assert storage.load_rawdata() == [
            raw_data,
            different_target_date,
            different_source,
            different_payload,
        ]
    finally:
        connection.close()


def test_save_records_ignores_duplicates_and_adds_only_new_records(
    tmp_path,
) -> None:
    storage = Storage(str(tmp_path / "test.db"))
    connection = storage.connect()
    first = Record(
        source="fusionsolar",
        timestamp=datetime(2026, 7, 20, tzinfo=timezone.utc),
        metric="productPower",
        value=42,
        unit="kW",
    )
    second = Record(
        source="fusionsolar",
        timestamp=datetime(2026, 7, 20, tzinfo=timezone.utc),
        metric="powerProfit",
        value=500,
        unit="JPY",
    )

    try:
        storage.save_records([first])
        storage.save_records([first])
        storage.save_records([first, second])

        assert storage.load_records() == [first, second]
    finally:
        connection.close()


def test_get_record_dates_converts_timezone_and_filters_range_and_source(
    tmp_path,
) -> None:
    storage = Storage(str(tmp_path / "test.db"))
    connection = storage.connect()
    records = [
        Record(
            "fusionsolar",
            datetime(2026, 7, 19, 15, tzinfo=timezone.utc),
            "productPower",
            1,
            "kW",
        ),
        Record(
            "fusionsolar",
            datetime(2026, 7, 20, 15, tzinfo=timezone.utc),
            "productPower",
            2,
            "kW",
        ),
        Record(
            "fusionsolar",
            datetime(2026, 7, 21, 15, tzinfo=timezone.utc),
            "productPower",
            3,
            "kW",
        ),
        Record(
            "other",
            datetime(2026, 7, 20, 15, tzinfo=timezone.utc),
            "productPower",
            4,
            "kW",
        ),
    ]

    try:
        storage.save_records(records)

        assert storage.get_record_dates(
            source="fusionsolar",
            start_date=date(2026, 7, 20),
            end_date=date(2026, 7, 21),
        ) == {date(2026, 7, 20), date(2026, 7, 21)}
    finally:
        connection.close()


def test_get_collected_dates_returns_matching_target_dates(tmp_path) -> None:
    storage = Storage(str(tmp_path / "test.db"))
    connection = storage.connect()
    raw_data_list = [
        RawData(
            source="fusionsolar",
            timestamp=datetime(2026, 7, 25, tzinfo=timezone.utc),
            payload={"day": day},
            target_date=date(2026, 7, day),
        )
        for day in (19, 20, 21, 22)
    ]
    raw_data_list.append(
        RawData(
            source="other",
            timestamp=datetime(2026, 7, 25, tzinfo=timezone.utc),
            payload={"day": 20},
            target_date=date(2026, 7, 20),
        )
    )
    raw_data_list.append(
        RawData(
            source="fusionsolar",
            timestamp=datetime(2026, 7, 25, tzinfo=timezone.utc),
            payload={"legacy": True},
        )
    )

    try:
        for raw_data in raw_data_list:
            storage.save_rawdata(raw_data)

        assert storage.get_collected_dates(
            source="fusionsolar",
            start_date=date(2026, 7, 20),
            end_date=date(2026, 7, 21),
        ) == {date(2026, 7, 20), date(2026, 7, 21)}
    finally:
        connection.close()
