from datetime import datetime, timedelta, timezone

from hedp.adapters.fusionsolar.modbus_qualification import (
    ModbusQualificationChecker,
)
from hedp.adapters.fusionsolar.modbus_record_builder import (
    FusionSolarModbusRecordBuilder,
)
from hedp.storage import RawData, Record


def _snapshot(
    timestamp,
    *,
    continuity_id="0123456789abcdef0123456789abcdef",
    continuity_reason="continuous",
):
    return RawData(
        source="fusionsolar_modbus_tcp",
        timestamp=timestamp,
        payload={
            "ranges": [
                {"name": "identity", "function_code": 3, "start_address": 30000, "registers": [0] * 15},
                {"name": "inverter_realtime", "function_code": 3, "start_address": 32064, "registers": [0] * 52},
                {"name": "storage_realtime", "function_code": 3, "start_address": 37000, "registers": [0] * 5},
            ]
        },
        metadata={
            "target_alias": "fixture",
            "continuity_id": continuity_id,
            "continuity_reason": continuity_reason,
        },
    )


def _records(raw_data):
    builder = FusionSolarModbusRecordBuilder()
    unique = {}
    for raw in raw_data:
        for record in builder.build(raw):
            unique.setdefault(record.to_json(), record)
    return list(unique.values())


def test_qualification_accepts_a_complete_single_epoch_24_hour_window():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    snapshots = [_snapshot(start + timedelta(minutes=5 * index)) for index in range(289)]

    report = ModbusQualificationChecker().evaluate(
        snapshots, _records(snapshots), now=snapshots[-1].timestamp
    )

    assert report.status == "qualified"
    assert report.successful_slots == 288
    assert report.complete_snapshots == 289
    assert report.as_dict()["continuity_evidence"] == "current_epoch_only"


def test_qualification_rejects_a_new_epoch_even_when_old_history_exists():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    old = [_snapshot(start + timedelta(minutes=5 * index)) for index in range(289)]
    current = [
        _snapshot(
            start + timedelta(hours=24, minutes=5 * index),
            continuity_id="fedcba9876543210fedcba9876543210",
        )
        for index in range(4)
    ]
    snapshots = old + current

    report = ModbusQualificationChecker().evaluate(
        snapshots, _records(snapshots), now=current[-1].timestamp
    )

    assert report.status == "not_qualified"
    assert report.reasons == ("insufficient_observed_hours", "success_rate_below_99_percent")
    assert report.total_snapshots == 4


def test_qualification_rejects_a_long_gap_and_incomplete_records():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    snapshots = [_snapshot(start + timedelta(minutes=5 * index)) for index in range(289)]
    del snapshots[100:104]
    records = _records(snapshots)
    records.pop()

    report = ModbusQualificationChecker().evaluate(
        snapshots, records, now=snapshots[-1].timestamp
    )

    assert report.status == "not_qualified"
    assert "success_rate_below_99_percent" in report.reasons
    assert "gap_over_15_minutes" in report.reasons
    assert "incomplete_records" in report.reasons


def test_qualification_does_not_retroactively_qualify_old_snapshots_without_epoch():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    snapshots = [
        RawData("fusionsolar_modbus_tcp", start + timedelta(minutes=5 * index), {})
        for index in range(289)
    ]

    report = ModbusQualificationChecker().evaluate(
        snapshots, [], now=snapshots[-1].timestamp
    )

    assert report.status == "not_qualified"
    assert report.reasons == ("continuity_evidence_missing",)


def test_qualification_accepts_exactly_99_percent_without_a_gap_over_boundary():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    snapshots = [_snapshot(start + timedelta(minutes=5 * index)) for index in range(289)]
    del snapshots[100:102]  # exactly 15 minutes from surrounding samples

    report = ModbusQualificationChecker().evaluate(
        snapshots, _records(snapshots), now=snapshots[-1].timestamp
    )

    assert report.status == "qualified"
    assert report.successful_slots == 286
    assert "gap_over_15_minutes" not in report.reasons


def test_qualification_rejects_same_slot_duplicates_that_hide_missing_slots():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    snapshots = [_snapshot(start + timedelta(minutes=5 * index)) for index in range(289)]
    del snapshots[100:103]
    snapshots.append(_snapshot(start + timedelta(minutes=104)))
    snapshots.sort(key=lambda item: item.timestamp)

    report = ModbusQualificationChecker().evaluate(
        snapshots, _records(snapshots), now=snapshots[-1].timestamp
    )

    assert report.successful_slots == 285
    assert "success_rate_below_99_percent" in report.reasons


def test_qualification_requires_raw_decode_and_record_units_and_values():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    snapshots = [_snapshot(start + timedelta(minutes=5 * index)) for index in range(289)]
    records = _records(snapshots)
    first = records[0]
    records[0] = Record(
        first.source, first.timestamp, first.metric, float("nan"), first.unit
    )
    snapshots[-1] = RawData(
        snapshots[-1].source,
        snapshots[-1].timestamp,
        {"ranges": []},
        metadata=snapshots[-1].metadata,
    )

    report = ModbusQualificationChecker().evaluate(
        snapshots, records, now=snapshots[-1].timestamp
    )

    assert report.status == "not_qualified"
    assert "incomplete_records" in report.reasons


def test_qualification_treats_stale_boundary_as_fresh_but_one_second_later_as_stale():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    snapshots = [_snapshot(start + timedelta(minutes=5 * index)) for index in range(289)]
    records = _records(snapshots)
    checker = ModbusQualificationChecker()

    at_boundary = checker.evaluate(
        snapshots, records, now=snapshots[-1].timestamp + timedelta(seconds=900)
    )
    after_boundary = checker.evaluate(
        snapshots, records, now=snapshots[-1].timestamp + timedelta(seconds=901)
    )

    assert at_boundary.latest_snapshot_fresh is True
    assert "latest_snapshot_delayed" not in at_boundary.reasons
    assert after_boundary.latest_snapshot_fresh is False
    assert "latest_snapshot_delayed" in after_boundary.reasons


def test_qualification_rejects_future_snapshot_evidence():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    snapshots = [_snapshot(start + timedelta(minutes=5 * index)) for index in range(289)]

    report = ModbusQualificationChecker().evaluate(
        snapshots, _records(snapshots), now=snapshots[-1].timestamp - timedelta(seconds=1)
    )

    assert report.status == "not_qualified"
    assert report.latest_snapshot_fresh is False
    assert "latest_snapshot_in_future" in report.reasons


def test_qualification_fails_closed_when_boot_evidence_was_unavailable():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    snapshots = [
        _snapshot(
            start + timedelta(minutes=5 * index),
            continuity_reason="boot_evidence_unavailable",
        )
        for index in range(289)
    ]

    report = ModbusQualificationChecker().evaluate(
        snapshots, _records(snapshots), now=snapshots[-1].timestamp
    )

    assert report.status == "not_qualified"
    assert "boot_evidence_unavailable" in report.reasons
