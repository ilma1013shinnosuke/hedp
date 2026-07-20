from datetime import date, datetime, timedelta, timezone
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


def test_run_battery_dc_saves_successes():
    collected = [Mock(spec=RawData), Mock(spec=RawData)]
    collector = Mock()
    collector.collect_modules.return_value = (collected, [(2, "failed")])
    storage = Mock()
    application = Application(
        None, storage, None, battery_dc_collector=collector
    )

    result = application.run_battery_dc("NE=1", "1,2", [1, 2, 3])

    assert result == (collected, [(2, "failed")])
    collector.collect_modules.assert_called_once_with(
        "NE=1", "1,2", [1, 2, 3]
    )
    assert storage.save_rawdata.call_args_list == [
        call(collected[0]),
        call(collected[1]),
    ]


def test_run_current_alarms_saves_all_pages():
    collected = [Mock(spec=RawData), Mock(spec=RawData)]
    collector = Mock()
    collector.collect_current_devices.return_value = (collected, [])
    storage = Mock()
    application = Application(None, storage, None, alarm_collector=collector)

    result = application.run_current_alarms(["NE=1"])

    assert result == (collected, [])
    collector.collect_current_devices.assert_called_once_with(["NE=1"])
    assert storage.save_rawdata.call_args_list == [
        call(collected[0]),
        call(collected[1]),
    ]


def test_battery_dc_quality_reports_missing_modules_and_invalid_response():
    storage = Mock()
    storage.load_rawdata.return_value = [
        RawData(
            "fusionsolar_battery_dc",
            datetime(2026, 7, 20, tzinfo=timezone.utc),
            {"success": True, "data": [{"id": 1}]},
            metadata={"device_dn": "NE=1", "module_id": 1},
        ),
        RawData(
            "fusionsolar_battery_dc",
            datetime(2026, 7, 20, 1, tzinfo=timezone.utc),
            {"success": True, "data": "invalid"},
            metadata={"device_dn": "NE=1", "module_id": 2},
        ),
    ]
    report = Application(None, storage, None).check_battery_dc_quality()
    assert report["collection_count"] == 2
    assert report["invalid_responses"] == 1
    assert report["missing_modules"] == ["3", "4"]
    assert report["issue_count"] == 3


def test_alarm_quality_reports_hits_and_missing_current_device():
    storage = Mock()
    storage.load_rawdata.return_value = [
        RawData(
            "fusionsolar_alarm_current",
            datetime(2026, 7, 20, tzinfo=timezone.utc),
            {"success": True, "data": {"hits": [{"alarmId": 1}]}},
            metadata={"device_dn": "NE=1", "page_number": 1},
        ),
        RawData(
            "fusionsolar_alarm_history",
            datetime(2026, 7, 20, tzinfo=timezone.utc),
            {"success": True, "data": {"hits": []}},
            metadata={"device_dn": "NE=2", "page_number": 1},
        ),
    ]
    report = Application(None, storage, None).check_alarm_quality(
        ["NE=1", "NE=2"]
    )
    assert report["total_hits"] == 1
    assert report["missing_current_devices"] == ["NE=2"]
    assert report["issue_count"] == 1


def test_realtime_snapshot_continues_independent_collectors():
    application = Application(None, Mock(), None)
    application.run_device_realtime = Mock(side_effect=RuntimeError("device"))
    application.run_battery_dc = Mock(return_value=([Mock()], []))
    application.run_current_alarms = Mock(return_value=([Mock()], []))

    result = application.run_realtime_snapshot(
        ["NE=1"], "NE=battery", "1,2"
    )

    assert "device_error" in result
    assert len(result["battery"][0]) == 1
    assert len(result["alarm"][0]) == 1
    application.run_battery_dc.assert_called_once_with(
        "NE=battery", "1,2", [1, 2, 3, 4]
    )
    application.run_current_alarms.assert_called_once_with(["NE=1"])


def test_battery_diagnose_detects_signal_id_set_changes():
    storage = Mock()
    storage.load_rawdata.return_value = [
        RawData(
            "fusionsolar_battery_dc",
            datetime(2026, 7, 20, hour, tzinfo=timezone.utc),
            {"success": True, "data": [{"id": signal_id}]},
            metadata={"device_dn": "NE=1", "module_id": 1},
        )
        for hour, signal_id in ((0, 10), (1, 11))
    ]
    report = Application(None, storage, None).diagnose_battery_dc()
    assert report["signal_ids_by_module"] == {"1": [11]}
    assert report["signal_id_changes_by_module"] == {"1": 1}
    assert report["latest_by_module"]["1"].startswith("2026-07-20T01:00")


def test_alarm_diagnose_reports_daily_history_gaps_and_pagination_issue():
    storage = Mock()
    current_metadata = {
        "device_dn": "NE=1",
        "collection_id": "current-run",
        "page_no": 1,
        "page_size": 10,
    }
    history_metadata = {
        "device_dn": "NE=1",
        "collection_id": "history-run",
        "page_no": 1,
        "page_size": 10,
        "target_date": "2026-07-19",
    }
    storage.load_rawdata.return_value = [
        RawData(
            "fusionsolar_alarm_current",
            datetime(2026, 7, 20, 0, minute, tzinfo=timezone.utc),
            {"success": True, "data": {"totalCount": 0, "hits": []}},
            metadata={**current_metadata, "collection_id": f"current-{minute}"},
        )
        for minute in (0, 15)
    ] + [
        RawData(
            "fusionsolar_alarm_history",
            datetime(2026, 7, 20, 1, tzinfo=timezone.utc),
            {"success": True, "data": {"totalCount": 2, "hits": [{}]}},
            metadata=history_metadata,
        )
    ]
    report = Application(None, storage, None).diagnose_alarms()
    assert report["history_by_date"] == {"2026-07-19": 1}
    assert report["current_gaps_by_device"] == {"NE=1": 1}
    assert report["pagination_issues"] == 1


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


def test_run_energy_balance_for_date_saves_only_raw_data() -> None:
    target_date = date(2026, 7, 20)
    raw_data = Mock(spec=RawData)
    collector = Mock()
    collector.collect_for_date.return_value = raw_data
    storage = Mock()
    record_builder = Mock()
    application = Application(
        Mock(), storage, record_builder, energy_balance_collector=collector
    )

    result = application.run_energy_balance_for_date(target_date)

    assert result is raw_data
    collector.collect_for_date.assert_called_once_with(target_date)
    storage.save_rawdata.assert_called_once_with(raw_data)
    storage.save_records.assert_not_called()
    record_builder.build.assert_not_called()


def test_run_energy_balance_range_saves_each_raw_data_only() -> None:
    raw_data_list = [Mock(spec=RawData), Mock(spec=RawData)]
    collector = Mock()
    collector.collect_range.return_value = raw_data_list
    storage = Mock()
    record_builder = Mock()
    application = Application(
        Mock(), storage, record_builder, energy_balance_collector=collector
    )

    result = application.run_energy_balance_range(
        date(2026, 7, 20), date(2026, 7, 21)
    )

    assert result is raw_data_list
    collector.collect_range.assert_called_once_with(
        date(2026, 7, 20), date(2026, 7, 21)
    )
    assert storage.save_rawdata.call_args_list == [
        call(raw_data_list[0]),
        call(raw_data_list[1]),
    ]
    storage.save_records.assert_not_called()
    record_builder.build.assert_not_called()


def test_find_missing_dates_returns_dates_in_order() -> None:
    storage = Mock()
    storage.get_record_dates.return_value = {
        date(2026, 7, 20),
        date(2026, 7, 22),
    }
    storage.get_collected_dates.return_value = {date(2026, 7, 23)}
    application = Application(Mock(), storage, Mock())

    result = application.find_missing_dates(
        date(2026, 7, 20), date(2026, 7, 23)
    )

    assert result == [date(2026, 7, 21)]
    storage.get_record_dates.assert_called_once_with(
        source="fusionsolar",
        start_date=date(2026, 7, 20),
        end_date=date(2026, 7, 23),
        timezone_name="Asia/Tokyo",
    )
    storage.get_collected_dates.assert_called_once_with(
        source="fusionsolar",
        start_date=date(2026, 7, 20),
        end_date=date(2026, 7, 23),
    )


def test_find_missing_dates_returns_empty_when_complete() -> None:
    storage = Mock()
    storage.get_record_dates.return_value = {
        date(2026, 7, 20),
    }
    storage.get_collected_dates.return_value = {date(2026, 7, 21)}
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


def _quality_records(timestamp: datetime) -> list[Record]:
    units = {
        "productPower": "kW",
        "inverterPower": "kW",
        "onGridPower": "kW",
        "buyPower": "kW",
        "powerProfit": "JPY",
    }
    return [
        Record("fusionsolar", timestamp, metric, 1, unit)
        for metric, unit in units.items()
    ]


def test_check_quality_returns_no_issues_for_normal_data() -> None:
    first = datetime(2026, 7, 20, tzinfo=timezone.utc)
    records = _quality_records(first) + _quality_records(
        first + timedelta(minutes=60)
    )
    storage = Mock()
    storage.load_records_for_range.return_value = records
    application = Application(Mock(), storage, Mock())

    report = application.check_quality(
        date(2026, 7, 20), date(2026, 7, 20)
    )

    assert report == {
        "duplicate_records": 0,
        "invalid_values": 0,
        "unexpected_metrics": [],
        "unexpected_units": 0,
        "missing_metric_points": [],
        "irregular_intervals": [],
        "summary": {
            "record_count": 10,
            "timestamp_count": 2,
            "first_timestamp": first.isoformat(),
            "last_timestamp": (first + timedelta(minutes=60)).isoformat(),
        },
    }


def test_check_quality_reports_all_quality_issues() -> None:
    first = datetime(2026, 7, 20, tzinfo=timezone.utc)
    second = first + timedelta(minutes=10)
    next_day = datetime(2026, 7, 21, tzinfo=timezone.utc)
    duplicate = _quality_records(first)[0]
    records = [
        *_quality_records(first),
        duplicate,
        duplicate,
        Record("fusionsolar", second, "productPower", float("nan"), "kW"),
        Record("fusionsolar", second, "inverterPower", float("inf"), "kW"),
        Record("fusionsolar", second, "onGridPower", 1, "W"),
        Record("fusionsolar", second, "unknown", 1, "kW"),
        *_quality_records(next_day),
    ]
    storage = Mock()
    storage.load_records_for_range.return_value = records
    application = Application(Mock(), storage, Mock())

    report = application.check_quality(
        date(2026, 7, 20), date(2026, 7, 21)
    )

    assert report["duplicate_records"] == 2
    assert report["invalid_values"] == 2
    assert report["unexpected_metrics"] == ["unknown"]
    assert report["unexpected_units"] == 2
    assert report["missing_metric_points"] == [
        {
            "timestamp": second.isoformat(),
            "missing_metrics": ["powerProfit"],
        }
    ]
    assert report["irregular_intervals"] == [
        {
            "previous": first.isoformat(),
            "current": second.isoformat(),
            "minutes": 10.0,
        }
    ]


def test_check_quality_treats_none_as_present_and_valid() -> None:
    timestamp = datetime(2026, 7, 20, tzinfo=timezone.utc)
    records = _quality_records(timestamp)
    records[0] = Record(
        "fusionsolar", timestamp, "productPower", None, "kW"
    )
    storage = Mock()
    storage.load_records_for_range.return_value = records

    report = Application(Mock(), storage, Mock()).check_quality(
        date(2026, 7, 20), date(2026, 7, 20)
    )

    assert report["invalid_values"] == 0
    assert report["missing_metric_points"] == []


def test_check_quality_treats_buy_power_as_optional() -> None:
    timestamp = datetime(2026, 7, 20, tzinfo=timezone.utc)
    records = [
        record
        for record in _quality_records(timestamp)
        if record.metric != "buyPower"
    ]
    storage = Mock()
    storage.load_records_for_range.return_value = records

    report = Application(Mock(), storage, Mock()).check_quality(
        date(2026, 7, 20), date(2026, 7, 20)
    )

    assert report["missing_metric_points"] == []


def test_check_quality_reports_missing_required_metric() -> None:
    timestamp = datetime(2026, 7, 20, tzinfo=timezone.utc)
    records = [
        record
        for record in _quality_records(timestamp)
        if record.metric not in {"buyPower", "inverterPower"}
    ]
    storage = Mock()
    storage.load_records_for_range.return_value = records

    report = Application(Mock(), storage, Mock()).check_quality(
        date(2026, 7, 20), date(2026, 7, 20)
    )

    assert report["missing_metric_points"] == [
        {
            "timestamp": timestamp.isoformat(),
            "missing_metrics": ["inverterPower"],
        }
    ]


@pytest.mark.parametrize("minutes", [5, 120, 180])
def test_check_quality_reports_non_hourly_interval(minutes) -> None:
    first = datetime(2026, 7, 20, tzinfo=timezone.utc)
    current = first + timedelta(minutes=minutes)
    storage = Mock()
    storage.load_records_for_range.return_value = [
        *_quality_records(first),
        *_quality_records(current),
    ]

    report = Application(Mock(), storage, Mock()).check_quality(
        date(2026, 7, 20), date(2026, 7, 20)
    )

    assert report["irregular_intervals"] == [
        {
            "previous": first.isoformat(),
            "current": current.isoformat(),
            "minutes": float(minutes),
        }
    ]


def test_check_quality_ignores_interval_across_tokyo_dates() -> None:
    first = datetime(2026, 7, 20, 14, 55, tzinfo=timezone.utc)
    current = first + timedelta(minutes=10)
    storage = Mock()
    storage.load_records_for_range.return_value = [
        *_quality_records(first),
        *_quality_records(current),
    ]

    report = Application(Mock(), storage, Mock()).check_quality(
        date(2026, 7, 20), date(2026, 7, 21)
    )

    assert report["irregular_intervals"] == []


def test_check_quality_returns_empty_summary_for_no_data() -> None:
    storage = Mock()
    storage.load_records_for_range.return_value = []

    report = Application(Mock(), storage, Mock()).check_quality(
        date(2026, 7, 20), date(2026, 7, 20)
    )

    assert report["summary"] == {
        "record_count": 0,
        "timestamp_count": 0,
        "first_timestamp": None,
        "last_timestamp": None,
    }
    assert report["missing_metric_points"] == []
    assert report["irregular_intervals"] == []


def test_check_quality_rejects_reverse_range() -> None:
    application = Application(Mock(), Mock(), Mock())

    with pytest.raises(ValueError):
        application.check_quality(date(2026, 7, 21), date(2026, 7, 20))


def test_check_quality_processes_150000_records_in_one_pass() -> None:
    class TrackedRecords(list):
        iterations = 0
        slices = 0

        def __iter__(self):
            self.iterations += 1
            return super().__iter__()

        def __getitem__(self, key):
            if isinstance(key, slice):
                self.slices += 1
            return super().__getitem__(key)

    first = datetime(2026, 1, 1, tzinfo=timezone.utc)
    records = TrackedRecords(
        record
        for point in range(30_000)
        for record in _quality_records(first + timedelta(minutes=60 * point))
    )
    storage = Mock()
    storage.load_records_for_range.return_value = records

    report = Application(Mock(), storage, Mock()).check_quality(
        date(2026, 1, 1), date(2026, 12, 31)
    )

    assert report["summary"]["record_count"] == 150_000
    assert report["duplicate_records"] == 0
    assert records.iterations == 1
    assert records.slices == 0


def test_diagnose_quality_aggregates_missing_and_irregular_details() -> None:
    application = Application(Mock(), Mock(), Mock())
    application.check_quality = Mock(
        return_value={
            "missing_metric_points": [
                {
                    "timestamp": "2026-01-01T15:00:00+00:00",
                    "missing_metrics": ["buyPower", "powerProfit"],
                },
                {
                    "timestamp": "2026-01-01T15:05:00+00:00",
                    "missing_metrics": ["buyPower", "powerProfit"],
                },
                {
                    "timestamp": "2026-02-01T03:00:00+00:00",
                    "missing_metrics": ["onGridPower"],
                },
            ],
            "irregular_intervals": [
                {
                    "previous": "2026-01-01T14:58:00+00:00",
                    "current": "2026-01-01T15:00:00+00:00",
                    "minutes": 2.0,
                },
                {
                    "previous": "2026-01-01T15:00:00+00:00",
                    "current": "2026-01-01T15:10:00+00:00",
                    "minutes": 10.0,
                },
                {
                    "previous": "2026-02-01T03:00:00+00:00",
                    "current": "2026-02-01T03:10:00+00:00",
                    "minutes": 10.0,
                },
            ],
        }
    )

    diagnosis = application.diagnose_quality(
        date(2026, 1, 1), date(2026, 2, 28)
    )

    assert diagnosis["missing_metrics_by_metric"] == {
        "buyPower": 2,
        "onGridPower": 1,
        "powerProfit": 2,
    }
    assert diagnosis["missing_combinations"] == [
        {"missing_metrics": ["buyPower", "powerProfit"], "count": 2},
        {"missing_metrics": ["onGridPower"], "count": 1},
    ]
    assert diagnosis["missing_by_hour"] == {"0": 2, "12": 1}
    assert diagnosis["missing_by_month"] == {"2026-01": 2, "2026-02": 1}
    assert diagnosis["irregular_intervals_by_minutes"] == {2.0: 1, 10.0: 2}
    assert diagnosis["irregular_intervals_shorter_than_5_minutes"] == 1
    assert diagnosis["irregular_intervals_longer_than_5_minutes"] == 2
    assert diagnosis["irregular_intervals_by_hour"] == {"0": 2, "12": 1}
    assert diagnosis["irregular_intervals_by_month"] == {
        "2026-01": 2,
        "2026-02": 1,
    }
    application.check_quality.assert_called_once_with(
        date(2026, 1, 1), date(2026, 2, 28)
    )


def test_diagnose_quality_limits_examples_to_20() -> None:
    missing_points = [
        {
            "timestamp": f"2026-01-01T00:{minute:02d}:00+00:00",
            "missing_metrics": ["buyPower"],
        }
        for minute in range(25)
    ]
    intervals = [
        {
            "previous": f"2026-01-01T00:{minute:02d}:00+00:00",
            "current": f"2026-01-01T00:{minute + 1:02d}:00+00:00",
            "minutes": 1.0,
        }
        for minute in range(25)
    ]
    application = Application(Mock(), Mock(), Mock())
    application.check_quality = Mock(
        return_value={
            "missing_metric_points": missing_points,
            "irregular_intervals": intervals,
        }
    )

    diagnosis = application.diagnose_quality(
        date(2026, 1, 1), date(2026, 1, 1)
    )

    assert diagnosis["missing_examples"] == missing_points[:20]
    assert diagnosis["irregular_interval_examples"] == intervals[:20]
