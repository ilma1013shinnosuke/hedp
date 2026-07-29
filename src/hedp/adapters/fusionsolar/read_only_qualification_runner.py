"""Finite, anonymous, read-only qualification for FusionSolar Modbus TCP.

This module deliberately bypasses the production storage and application
entrypoints.  It reads only the fixed, approved register ranges and persists
only the common qualification harness' anonymous evidence.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import signal
from threading import Event
import time

from hedp.adapters.fusionsolar.modbus_collector import (
    FusionSolarModbusCollector,
)
from hedp.adapters.fusionsolar.modbus_profiles import SUN2000_JPL1_RANGES
from hedp.adapters.fusionsolar.modbus_record_builder import (
    FusionSolarModbusRecordBuilder,
)
from hedp.adapters.fusionsolar.modbus_tcp import ReadOnlyModbusTcpClient
from hedp.adapters.read_only_qualification_harness import (
    QualificationPlan,
    QualificationProbe,
    QualificationProbeError,
    QualificationProbeResult,
    QualificationRunStatus,
    QualificationStage,
    QualificationTestStore,
    ReadOnlyQualificationHarness,
)
from hedp.configuration import Configuration
from hedp.storage import RawData, Record


_SOURCE = "fusionsolar_modbus_tcp"
_SAMPLE_TIMEOUT_SECONDS = 12.0
_CLIENT_TIMEOUT_SECONDS = 3.0
_EXPECTED_METRICS = {
    metric: unit
    for metric, unit in FusionSolarModbusRecordBuilder.METRICS.values()
}


class LiveFusionSolarQualificationProbe:
    """Collect and validate one bounded read-only FusionSolar observation."""

    def __init__(
        self,
        collector: FusionSolarModbusCollector,
        *,
        record_builder: FusionSolarModbusRecordBuilder | None = None,
    ) -> None:
        self._collector = collector
        self._record_builder = record_builder or FusionSolarModbusRecordBuilder()
        self._failure_started_at: float | None = None

    def collect(self) -> QualificationProbeResult:
        try:
            raw_data = self._collector.collect()
            records = self._record_builder.build(raw_data)
            validate_records(records, raw_data)
        except Exception:
            if self._failure_started_at is None:
                self._failure_started_at = time.monotonic()
            raise
        recovery_status = "not_required"
        recovery_elapsed_ms = 0
        if self._failure_started_at is not None:
            recovery_status = "recovered"
            recovery_elapsed_ms = min(
                300_000,
                max(
                    0,
                    int(
                        (time.monotonic() - self._failure_started_at)
                        * 1_000
                    ),
                ),
            )
            self._failure_started_at = None
        return QualificationProbeResult(
            raw_data=raw_data,
            attempt_count=1,
            rediscovery_attempt_count=0,
            recovery_status=recovery_status,
            recovery_elapsed_ms=recovery_elapsed_ms,
        )


def validate_records(records: Sequence[Record], raw_data: RawData) -> None:
    """Require the exact confirmed metric contract without exposing values."""
    observed: dict[str, str] = {}
    for record in records:
        if record.source != raw_data.source or record.timestamp != raw_data.timestamp:
            raise QualificationProbeError("metric_contract_mismatch")
        if record.metric not in _EXPECTED_METRICS:
            raise QualificationProbeError("metric_unknown")
        if record.metric in observed:
            raise QualificationProbeError("metric_duplicate")
        if isinstance(record.value, bool) or not isinstance(record.value, (int, float)):
            raise QualificationProbeError("metric_value_invalid")
        if not math.isfinite(float(record.value)):
            raise QualificationProbeError("metric_value_invalid")
        if record.unit != _EXPECTED_METRICS[record.metric]:
            raise QualificationProbeError("metric_contract_mismatch")
        observed[record.metric] = record.unit
    if observed.keys() != _EXPECTED_METRICS.keys():
        raise QualificationProbeError("metric_missing")


def build_plan(
    stage: QualificationStage,
    *,
    run_id: str,
    started_at: datetime,
) -> QualificationPlan:
    """Build the release qualification stages with explicit finite bounds."""
    if stage is QualificationStage.SINGLE:
        duration = timedelta(seconds=_SAMPLE_TIMEOUT_SECONDS)
        interval = duration
        samples = 1
        failures = 1
    elif stage is QualificationStage.SHORT:
        duration = timedelta(minutes=15)
        interval = timedelta(minutes=5)
        samples = 3
        failures = 3
    else:
        duration = timedelta(hours=24)
        interval = timedelta(minutes=5)
        samples = 288
        failures = 3
    return QualificationPlan(
        run_id=run_id,
        source=_SOURCE,
        stage=stage,
        started_at=started_at,
        duration=duration,
        sample_interval=interval,
        maximum_samples=samples,
        per_sample_timeout_seconds=_SAMPLE_TIMEOUT_SECONDS,
        maximum_failures=failures,
        maximum_attempts_per_sample=1,
        maximum_rediscovery_attempts_per_sample=0,
    )


def execute_qualification(
    *,
    database_path: Path,
    plan: QualificationPlan,
    probe: QualificationProbe,
    stop_requested: Callable[[], bool] = lambda: False,
) -> dict[str, object]:
    """Execute against the dedicated qualification store and return a summary."""
    with QualificationTestStore(database_path) as store:
        summary = ReadOnlyQualificationHarness(store).run(
            plan,
            probe,
            stop_requested=stop_requested,
        )
    return summary.as_dict()


def _live_probe() -> LiveFusionSolarQualificationProbe:
    configuration = Configuration.modbus_from_environment()
    client = ReadOnlyModbusTcpClient(
        configuration.host,
        port=configuration.port,
        unit_id=configuration.unit_id,
        timeout_seconds=_CLIENT_TIMEOUT_SECONDS,
    )
    collector = FusionSolarModbusCollector(
        client,
        target_alias="solar-inverter",
        register_ranges=SUN2000_JPL1_RANGES,
    )
    return LiveFusionSolarQualificationProbe(collector)


def _parse_started_at(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("started-at must include a timezone")
    return parsed.astimezone(timezone.utc)


def _generated_run_id(stage: QualificationStage, started_at: datetime) -> str:
    return f"fusionsolar-{stage.value}-{started_at:%Y%m%d%H%M%S}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run finite anonymous FusionSolar read-only qualification."
    )
    parser.add_argument(
        "--stage",
        required=True,
        choices=tuple(item.value for item in QualificationStage),
    )
    parser.add_argument("--database", required=True)
    parser.add_argument("--run-id")
    parser.add_argument(
        "--started-at",
        help="Timezone-aware ISO timestamp; reuse with --run-id when resuming.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    event = Event()

    def request_stop(_signum: int, _frame: object) -> None:
        event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        arguments = _parser().parse_args(argv)
        database_path = Path(arguments.database)
        if not database_path.is_absolute():
            raise ValueError("database must be an absolute path")
        stage = QualificationStage(arguments.stage)
        started_at = _parse_started_at(arguments.started_at)
        run_id = arguments.run_id or _generated_run_id(stage, started_at)
        plan = build_plan(stage, run_id=run_id, started_at=started_at)
        summary = execute_qualification(
            database_path=database_path,
            plan=plan,
            probe=_live_probe(),
            stop_requested=event.is_set,
        )
        print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
        status = summary.get("status")
        if status == QualificationRunStatus.COMPLETED.value:
            return 0
        if status == QualificationRunStatus.INTERRUPTED.value:
            return 2
        return 1
    except (OSError, RuntimeError, TypeError, ValueError):
        print(
            json.dumps(
                {
                    "status": QualificationRunStatus.FAILED.value,
                    "reason": "qualification_unavailable",
                },
                separators=(",", ":"),
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
