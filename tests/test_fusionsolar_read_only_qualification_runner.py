from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
import struct

import pytest

from hedp.adapters.fusionsolar.read_only_qualification_runner import (
    LiveFusionSolarQualificationProbe,
    build_plan,
    execute_qualification,
    validate_records,
)
from hedp.adapters.fusionsolar.modbus_record_builder import (
    FusionSolarModbusRecordBuilder,
)
from hedp.adapters.read_only_qualification_harness import (
    QualificationProbeError,
    QualificationStage,
)
from hedp.storage import RawData, Record


def _valid_raw() -> RawData:
    identity = list(
        struct.unpack(
            ">15H",
            b"SUN2000-4.95KTL-JPL1".ljust(30, b"\0"),
        )
    )
    realtime = [0] * 52
    realtime[0:2] = [0, 2500]
    realtime[16:18] = [0, 1800]
    realtime[21] = 5998
    realtime[23] = 395
    realtime[25] = 0x0200
    realtime[42:44] = [0, 12345]
    realtime[50:52] = [0, 678]
    storage = [2, 0, 900, 0, 825]
    return RawData(
        source="fusionsolar_modbus_tcp",
        timestamp=datetime(2026, 7, 28, tzinfo=timezone.utc),
        payload={
            "ranges": [
                {
                    "name": "identity",
                    "function_code": 3,
                    "start_address": 30000,
                    "registers": identity,
                },
                {
                    "name": "inverter_realtime",
                    "function_code": 3,
                    "start_address": 32064,
                    "registers": realtime,
                },
                {
                    "name": "storage_realtime",
                    "function_code": 3,
                    "start_address": 37000,
                    "registers": storage,
                },
            ]
        },
        metadata={"target_alias": "solar-inverter"},
    )


class _Collector:
    def __init__(self, raw_data: RawData) -> None:
        self.raw_data = raw_data

    def collect(self) -> RawData:
        return self.raw_data


@pytest.mark.parametrize(
    ("stage", "minutes", "samples"),
    (
        (QualificationStage.SHORT, 15, 3),
        (QualificationStage.DAY_24, 24 * 60, 288),
    ),
)
def test_build_plan_uses_release_bounds(
    stage: QualificationStage,
    minutes: int,
    samples: int,
) -> None:
    started_at = datetime(2026, 7, 28, tzinfo=timezone.utc)

    plan = build_plan(stage, run_id=f"test-{stage.value}", started_at=started_at)

    assert plan.duration.total_seconds() == minutes * 60
    assert plan.maximum_samples == samples
    assert plan.maximum_attempts_per_sample == 1
    assert plan.maximum_rediscovery_attempts_per_sample == 0


def test_live_probe_requires_exact_confirmed_metrics() -> None:
    result = LiveFusionSolarQualificationProbe(_Collector(_valid_raw())).collect()

    assert result.raw_data.source == "fusionsolar_modbus_tcp"
    assert result.attempt_count == 1
    assert result.rediscovery_attempt_count == 0
    assert result.recovery_status == "not_required"


def test_validate_records_distinguishes_invalid_metric_value() -> None:
    raw_data = _valid_raw()
    invalid = FusionSolarModbusRecordBuilder().build(raw_data)
    invalid[0] = Record(
        source=raw_data.source,
        timestamp=raw_data.timestamp,
        metric=invalid[0].metric,
        value=math.nan,
        unit=invalid[0].unit,
    )

    with pytest.raises(QualificationProbeError) as captured:
        validate_records(invalid, raw_data)

    assert captured.value.reason_code == "metric_value_invalid"


def test_validate_records_distinguishes_missing_metric() -> None:
    raw_data = _valid_raw()
    missing = FusionSolarModbusRecordBuilder().build(raw_data)[:-1]

    with pytest.raises(QualificationProbeError) as captured:
        validate_records(missing, raw_data)

    assert captured.value.reason_code == "metric_missing"


def test_validate_records_rejects_unknown_extra_metric() -> None:
    raw_data = _valid_raw()
    valid_records = FusionSolarModbusRecordBuilder().build(raw_data)
    invalid = [
        *valid_records,
        Record(
            source=raw_data.source,
            timestamp=raw_data.timestamp,
            metric="unexpected_metric",
            value=1.0,
            unit=None,
        ),
    ]

    with pytest.raises(QualificationProbeError) as captured:
        validate_records(invalid, raw_data)

    assert captured.value.reason_code == "metric_unknown"


def test_validate_records_distinguishes_duplicate_metric() -> None:
    raw_data = _valid_raw()
    records = FusionSolarModbusRecordBuilder().build(raw_data)

    with pytest.raises(QualificationProbeError) as captured:
        validate_records([*records, records[0]], raw_data)

    assert captured.value.reason_code == "metric_duplicate"


def test_validate_records_distinguishes_contract_mismatch() -> None:
    raw_data = _valid_raw()
    records = FusionSolarModbusRecordBuilder().build(raw_data)
    records[0] = Record(
        source=raw_data.source,
        timestamp=raw_data.timestamp,
        metric=records[0].metric,
        value=records[0].value,
        unit="unexpected-unit",
    )

    with pytest.raises(QualificationProbeError) as captured:
        validate_records(records, raw_data)

    assert captured.value.reason_code == "metric_contract_mismatch"


def test_live_probe_marks_first_good_sample_after_failure_as_recovered() -> None:
    raw_data = _valid_raw()

    class RecoveringBuilder:
        def __init__(self) -> None:
            self.calls = 0

        def build(self, raw: RawData) -> list[Record]:
            self.calls += 1
            records = FusionSolarModbusRecordBuilder().build(raw)
            return records[:-1] if self.calls == 1 else records

    probe = LiveFusionSolarQualificationProbe(
        _Collector(raw_data),
        record_builder=RecoveringBuilder(),  # type: ignore[arg-type]
    )

    with pytest.raises(QualificationProbeError) as captured:
        probe.collect()
    recovered = probe.collect()

    assert captured.value.reason_code == "metric_missing"
    assert recovered.recovery_status == "recovered"
    assert recovered.recovery_elapsed_ms >= 0


def test_harness_persists_safe_contract_failure_reason(tmp_path: Path) -> None:
    raw_data = _valid_raw()

    class MissingBuilder:
        def build(self, raw: RawData) -> list[Record]:
            return FusionSolarModbusRecordBuilder().build(raw)[:-1]

    database = tmp_path / "fusionsolar-missing.qualification.sqlite3"
    started_at = datetime.now(timezone.utc)
    plan = build_plan(
        QualificationStage.SINGLE,
        run_id="fusionsolar-missing-test",
        started_at=started_at,
    )

    summary = execute_qualification(
        database_path=database,
        plan=plan,
        probe=LiveFusionSolarQualificationProbe(
            _Collector(raw_data),
            record_builder=MissingBuilder(),  # type: ignore[arg-type]
        ),
    )

    assert summary["status"] == "failed"
    assert summary["failure_evidence"][0]["reason_codes"] == ["metric_missing"]


def test_single_run_stores_only_anonymous_qualification_evidence(
    tmp_path: Path,
) -> None:
    database = tmp_path / "fusionsolar-single.qualification.sqlite3"
    started_at = datetime.now(timezone.utc)
    plan = build_plan(
        QualificationStage.SINGLE,
        run_id="fusionsolar-single-test",
        started_at=started_at,
    )

    summary = execute_qualification(
        database_path=database,
        plan=plan,
        probe=LiveFusionSolarQualificationProbe(_Collector(_valid_raw())),
    )

    assert summary["status"] == "completed"
    assert summary["qualified_samples"] == 1
    assert summary["failed_samples"] == 0
    database_bytes = database.read_bytes()
    for forbidden in (
        b"SUN2000",
        b"solar-inverter",
        b"32064",
        b"37000",
        b"192.168.",
    ):
        assert forbidden not in database_bytes
    with sqlite3.connect(database) as connection:
        payload = connection.execute(
            "SELECT plan_json FROM qualification_runs"
        ).fetchone()
    assert payload is not None
    assert json.loads(payload[0])["source"] == "fusionsolar_modbus_tcp"
