"""Read-only evidence checker for the Modbus 24-hour cutover gate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Iterable

from hedp.adapters.fusionsolar.modbus_record_builder import (
    FusionSolarModbusRecordBuilder,
)
from hedp.storage import RawData, Record


@dataclass(frozen=True)
class ModbusQualificationReport:
    """Aggregate-only result; it never exposes timestamps, payloads, or IDs."""

    status: str
    reasons: tuple[str, ...]
    observed_hours_bucket: str
    expected_slots: int
    successful_slots: int
    success_rate_percent: float
    complete_snapshots: int
    total_snapshots: int
    latest_snapshot_fresh: bool
    continuity_evidence: str

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reasons": list(self.reasons),
            "observed_hours_bucket": self.observed_hours_bucket,
            "expected_slots": self.expected_slots,
            "successful_slots": self.successful_slots,
            "success_rate_percent": self.success_rate_percent,
            "complete_snapshots": self.complete_snapshots,
            "total_snapshots": self.total_snapshots,
            "latest_snapshot_fresh": self.latest_snapshot_fresh,
            "continuity_evidence": self.continuity_evidence,
        }


class ModbusQualificationChecker:
    """Evaluate one post-reboot/scheduling-gap continuity identifier.

    The continuity identifier comes from the private runner sentinel, not from the device.  A
    missing identifier is intentionally insufficient evidence: existing historical
    snapshots remain valuable, but cannot satisfy a new continuous-operation
    gate retroactively.
    """

    source = "fusionsolar_modbus_tcp"
    interval_seconds = 300
    required_hours = 24
    maximum_gap_seconds = 15 * 60
    freshness_seconds = 15 * 60

    def evaluate(
        self,
        raw_data: Iterable[RawData],
        records: Iterable[Record],
        *,
        now: datetime | None = None,
    ) -> ModbusQualificationReport:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        snapshots = sorted(
            (item for item in raw_data if item.source == self.source),
            key=lambda item: item.timestamp,
        )
        if not snapshots:
            return self._empty("no_snapshots")
        latest = snapshots[-1]
        continuity_id = self._continuity_id(latest)
        if continuity_id is None:
            return self._empty("continuity_evidence_missing")
        continuity_snapshots = [
            item for item in snapshots
            if self._continuity_id(item) == continuity_id
        ]
        if not continuity_snapshots:
            return self._empty("continuity_evidence_missing")
        earliest = continuity_snapshots[0]
        observed_seconds = max(0.0, (latest.timestamp - earliest.timestamp).total_seconds())
        expected_slots = self.required_hours * 60 * 60 // self.interval_seconds
        latest_slot = int(latest.timestamp.timestamp()) // self.interval_seconds
        required_slots = set(range(latest_slot - expected_slots + 1, latest_slot + 1))
        window_start = latest.timestamp - timedelta(hours=self.required_hours)
        current = [
            item for item in continuity_snapshots if item.timestamp >= window_start
        ]
        successful_slots = {
            int(item.timestamp.timestamp()) // self.interval_seconds
            for item in current
        } & required_slots
        rate = round(len(successful_slots) * 100 / expected_slots, 2)
        expected_metrics = {
            metric: unit
            for metric, unit in FusionSolarModbusRecordBuilder.METRICS.values()
        }
        records_by_timestamp: dict[datetime, list[Record]] = {}
        for record in records:
            if record.source == self.source:
                records_by_timestamp.setdefault(record.timestamp, []).append(record)
        complete_snapshots = sum(
            self._records_match_raw(
                item,
                records_by_timestamp.get(item.timestamp, []),
                expected_metrics,
            )
            for item in current
        )
        gaps = [
            (right.timestamp - left.timestamp).total_seconds()
            for left, right in zip(current, current[1:])
        ]
        latest_age = (now - latest.timestamp).total_seconds()
        reasons: list[str] = []
        if observed_seconds < self.required_hours * 60 * 60:
            reasons.append("insufficient_observed_hours")
        if len(successful_slots) * 100 < expected_slots * 99:
            reasons.append("success_rate_below_99_percent")
        if any(gap > self.maximum_gap_seconds for gap in gaps):
            reasons.append("gap_over_15_minutes")
        if complete_snapshots != len(current):
            reasons.append("incomplete_records")
        if latest_age < 0:
            reasons.append("latest_snapshot_in_future")
        elif latest_age > self.freshness_seconds:
            reasons.append("latest_snapshot_delayed")
        if not self._has_boot_evidence(continuity_snapshots):
            reasons.append("boot_evidence_unavailable")
        return ModbusQualificationReport(
            status="qualified" if not reasons else "not_qualified",
            reasons=tuple(reasons),
            observed_hours_bucket=self._hours_bucket(observed_seconds),
            expected_slots=expected_slots,
            successful_slots=len(successful_slots),
            success_rate_percent=rate,
            complete_snapshots=complete_snapshots,
            total_snapshots=len(current),
            latest_snapshot_fresh=0 <= latest_age <= self.freshness_seconds,
            continuity_evidence="current_epoch_only",
        )

    @staticmethod
    def _continuity_id(item: RawData) -> str | None:
        metadata = item.metadata
        if not isinstance(metadata, dict):
            return None
        value = metadata.get("continuity_id")
        if not isinstance(value, str) or len(value) != 32:
            return None
        if any(character not in "0123456789abcdef" for character in value):
            return None
        return value

    @staticmethod
    def _has_boot_evidence(items: Iterable[RawData]) -> bool:
        trusted = {
            "initial",
            "continuous",
            "boot_changed",
            "scheduling_gap",
            "boot_evidence_recovered",
        }
        reasons = [
            item.metadata.get("continuity_reason")
            for item in items
            if isinstance(item.metadata, dict)
        ]
        return bool(reasons) and all(reason in trusted for reason in reasons)

    @staticmethod
    def _records_match_raw(
        raw_data: RawData,
        records: list[Record],
        expected_metrics: dict[str, str],
    ) -> bool:
        """Require an exact, finite, unit-correct decode of this RawData."""
        try:
            decoded = FusionSolarModbusRecordBuilder().build(raw_data)
        except (KeyError, TypeError, ValueError):
            return False
        if len(decoded) != len(expected_metrics) or len(records) != len(expected_metrics):
            return False
        decoded_by_metric = {record.metric: record for record in decoded}
        actual_by_metric = {record.metric: record for record in records}
        if len(decoded_by_metric) != len(expected_metrics) or len(actual_by_metric) != len(expected_metrics):
            return False
        for metric, unit in expected_metrics.items():
            decoded_record = decoded_by_metric.get(metric)
            actual = actual_by_metric.get(metric)
            if decoded_record is None or actual is None or actual.unit != unit:
                return False
            if not isinstance(actual.value, (int, float)) or isinstance(actual.value, bool):
                return False
            if not math.isfinite(actual.value):
                return False
            if actual.value != decoded_record.value or decoded_record.unit != unit:
                return False
        return True

    def _empty(self, reason: str) -> ModbusQualificationReport:
        return ModbusQualificationReport(
            status="not_qualified",
            reasons=(reason,),
            observed_hours_bucket="under_24h",
            expected_slots=self.required_hours * 60 * 60 // self.interval_seconds,
            successful_slots=0,
            success_rate_percent=0.0,
            complete_snapshots=0,
            total_snapshots=0,
            latest_snapshot_fresh=False,
            continuity_evidence="missing",
        )

    @staticmethod
    def _hours_bucket(seconds: float) -> str:
        if seconds < 24 * 60 * 60:
            return "under_24h"
        if seconds < 48 * 60 * 60:
            return "24_to_48h"
        return "48h_or_more"
