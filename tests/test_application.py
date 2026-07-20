from datetime import date, datetime, timezone
from unittest.mock import Mock, call

import pytest

from hedp.application import Application
from hedp.raw_data import RawData
from hedp.record import Record


def test_run_collects_then_saves_and_returns_same_raw_data() -> None:
    raw_data = RawData(
        source="fusionsolar",
        timestamp=datetime(2026, 7, 20, tzinfo=timezone.utc),
        payload={"value": 42},
    )
    collector = Mock()
    collector.collect.return_value = raw_data
    records = [
        Record(
            source="fusionsolar",
            timestamp=raw_data.timestamp,
            metric="productPower",
            value=42,
            unit="kW",
        )
    ]
    record_builder = Mock()
    record_builder.build.return_value = records
    storage = Mock()
    calls = Mock()
    calls.attach_mock(collector.collect, "collect")
    calls.attach_mock(storage.save_rawdata, "save_rawdata")
    calls.attach_mock(record_builder.build, "build")
    calls.attach_mock(storage.save_records, "save_records")
    application = Application(collector, storage, record_builder)

    result = application.run()

    collector.collect.assert_called_once_with()
    storage.save_rawdata.assert_called_once_with(raw_data)
    record_builder.build.assert_called_once_with(raw_data)
    storage.save_records.assert_called_once_with(records)
    assert result is raw_data
    assert calls.mock_calls == [
        call.collect(),
        call.save_rawdata(raw_data),
        call.build(raw_data),
        call.save_records(records),
    ]


def test_run_range_processes_each_raw_data_in_order() -> None:
    raw_data_list = [
        RawData(
            source="fusionsolar",
            timestamp=datetime(2026, 7, day, tzinfo=timezone.utc),
            payload={"day": day},
        )
        for day in (20, 21, 22)
    ]
    records = [[Mock(name=f"record-{day}")] for day in (20, 21, 22)]
    collector = Mock()
    collector.collect_range.return_value = raw_data_list
    storage = Mock()
    record_builder = Mock()
    record_builder.build.side_effect = records
    calls = Mock()
    calls.attach_mock(collector.collect_range, "collect_range")
    calls.attach_mock(storage.save_rawdata, "save_rawdata")
    calls.attach_mock(record_builder.build, "build")
    calls.attach_mock(storage.save_records, "save_records")
    application = Application(collector, storage, record_builder)

    result = application.run_range(date(2026, 7, 20), date(2026, 7, 22))

    assert result is raw_data_list
    assert calls.mock_calls == [
        call.collect_range(date(2026, 7, 20), date(2026, 7, 22)),
        call.save_rawdata(raw_data_list[0]),
        call.build(raw_data_list[0]),
        call.save_records(records[0]),
        call.save_rawdata(raw_data_list[1]),
        call.build(raw_data_list[1]),
        call.save_records(records[1]),
        call.save_rawdata(raw_data_list[2]),
        call.build(raw_data_list[2]),
        call.save_records(records[2]),
    ]


def test_run_range_stops_after_processing_error() -> None:
    raw_data_list = [
        RawData(
            source="fusionsolar",
            timestamp=datetime(2026, 7, day, tzinfo=timezone.utc),
            payload={"day": day},
        )
        for day in (20, 21, 22)
    ]
    first_records = [Mock(name="record-20")]
    collector = Mock()
    collector.collect_range.return_value = raw_data_list
    storage = Mock()
    record_builder = Mock()
    record_builder.build.side_effect = [first_records, RuntimeError("failed")]
    calls = Mock()
    calls.attach_mock(storage.save_rawdata, "save_rawdata")
    calls.attach_mock(record_builder.build, "build")
    calls.attach_mock(storage.save_records, "save_records")
    application = Application(collector, storage, record_builder)

    with pytest.raises(RuntimeError, match="failed"):
        application.run_range(date(2026, 7, 20), date(2026, 7, 22))

    assert calls.mock_calls == [
        call.save_rawdata(raw_data_list[0]),
        call.build(raw_data_list[0]),
        call.save_records(first_records),
        call.save_rawdata(raw_data_list[1]),
        call.build(raw_data_list[1]),
    ]


def test_run_range_propagates_collection_error() -> None:
    collector = Mock()
    error = ValueError("invalid range")
    collector.collect_range.side_effect = error
    storage = Mock()
    record_builder = Mock()
    application = Application(collector, storage, record_builder)

    with pytest.raises(ValueError) as raised:
        application.run_range(date(2026, 7, 22), date(2026, 7, 20))

    assert raised.value is error
    storage.save_rawdata.assert_not_called()
    record_builder.build.assert_not_called()
    storage.save_records.assert_not_called()


def test_find_missing_dates_returns_dates_in_order() -> None:
    storage = Mock()
    storage.get_record_dates.return_value = {
        date(2026, 7, 20),
        date(2026, 7, 22),
    }
    application = Application(Mock(), storage, Mock())

    result = application.find_missing_dates(
        date(2026, 7, 20), date(2026, 7, 23)
    )

    assert result == [date(2026, 7, 21), date(2026, 7, 23)]
    storage.get_record_dates.assert_called_once_with(
        source="fusionsolar",
        start_date=date(2026, 7, 20),
        end_date=date(2026, 7, 23),
        timezone_name="Asia/Tokyo",
    )


def test_find_missing_dates_returns_empty_when_complete() -> None:
    storage = Mock()
    storage.get_record_dates.return_value = {
        date(2026, 7, 20),
        date(2026, 7, 21),
    }
    application = Application(Mock(), storage, Mock())

    assert application.find_missing_dates(
        date(2026, 7, 20), date(2026, 7, 21)
    ) == []


def test_find_missing_dates_rejects_reverse_range() -> None:
    application = Application(Mock(), Mock(), Mock())

    with pytest.raises(ValueError):
        application.find_missing_dates(
            date(2026, 7, 21), date(2026, 7, 20)
        )


def test_backfill_missing_processes_only_missing_dates_in_order() -> None:
    missing_dates = [date(2026, 7, 21), date(2026, 7, 23)]
    raw_data_list = [
        RawData(
            source="fusionsolar",
            timestamp=datetime(2026, 7, day, tzinfo=timezone.utc),
            payload={"day": day},
        )
        for day in (21, 23)
    ]
    records = [[Mock(name="records-21")], [Mock(name="records-23")]]
    collector = Mock()
    collector.collect_for_date.side_effect = raw_data_list
    storage = Mock()
    record_builder = Mock()
    record_builder.build.side_effect = records
    application = Application(collector, storage, record_builder)
    application.find_missing_dates = Mock(return_value=missing_dates)
    calls = Mock()
    calls.attach_mock(collector.collect_for_date, "collect_for_date")
    calls.attach_mock(storage.save_rawdata, "save_rawdata")
    calls.attach_mock(record_builder.build, "build")
    calls.attach_mock(storage.save_records, "save_records")

    result = application.backfill_missing(
        date(2026, 7, 20), date(2026, 7, 23)
    )

    assert result == raw_data_list
    assert calls.mock_calls == [
        call.collect_for_date(missing_dates[0]),
        call.save_rawdata(raw_data_list[0]),
        call.build(raw_data_list[0]),
        call.save_records(records[0]),
        call.collect_for_date(missing_dates[1]),
        call.save_rawdata(raw_data_list[1]),
        call.build(raw_data_list[1]),
        call.save_records(records[1]),
    ]


def test_backfill_missing_stops_after_error() -> None:
    missing_dates = [date(2026, 7, 21), date(2026, 7, 22)]
    raw_data = RawData(
        source="fusionsolar",
        timestamp=datetime(2026, 7, 21, tzinfo=timezone.utc),
        payload={"day": 21},
    )
    collector = Mock()
    collector.collect_for_date.return_value = raw_data
    storage = Mock()
    storage.save_rawdata.side_effect = RuntimeError("failed")
    record_builder = Mock()
    application = Application(collector, storage, record_builder)
    application.find_missing_dates = Mock(return_value=missing_dates)

    with pytest.raises(RuntimeError, match="failed"):
        application.backfill_missing(
            date(2026, 7, 21), date(2026, 7, 22)
        )

    collector.collect_for_date.assert_called_once_with(missing_dates[0])
    record_builder.build.assert_not_called()
    storage.save_records.assert_not_called()
