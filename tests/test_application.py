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
