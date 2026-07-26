"""Privacy-safe Qrio read collection without operation capabilities."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Callable

from hedp.observations import ObservationTime, ObservedValue
from hedp.storage import RawData

from .models import LockHealth
from .normalizer import normalize_health, normalize_history, normalize_status
from .reader import QrioReader


class QrioReadOnlyCollector:
    """Collect status, health, and history while removing household identifiers."""

    source = "qrio_read_only"

    def __init__(
        self,
        reader: QrioReader,
        *,
        source_lock_id: str,
        target_ref: str,
        history_page: int = 1,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if not source_lock_id:
            raise ValueError("source_lock_id must not be empty")
        if not target_ref:
            raise ValueError("target_ref must not be empty")
        if history_page < 1:
            raise ValueError("history_page must be positive")
        self._reader = reader
        self._source_lock_id = source_lock_id
        self._target_ref = target_ref
        self._history_page = history_page
        self._clock = clock

    def collect(self) -> RawData:
        received_at = self._clock()
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        timestamp = received_at.isoformat()
        time = ObservationTime(timestamp, timestamp)

        status_response = self._reader.status(self._source_lock_id)
        health_response = self._reader.health()
        history_response = self._reader.history(
            self._source_lock_id,
            page=self._history_page,
        )
        status = normalize_status(
            status_response,
            target_ref=self._target_ref,
            time=time,
        )
        health = normalize_health(
            health_response,
            aliases={self._source_lock_id: self._target_ref},
            time=time,
        )
        history = normalize_history(
            history_response,
            target_ref=self._target_ref,
            received_at=timestamp,
        )

        return RawData(
            source=self.source,
            timestamp=received_at,
            payload={
                "status": _reading(status.position),
                "health": {
                    "quality": health.quality.value,
                    "invalid_count": health.invalid_count,
                    "unmapped_count": health.unmapped_count,
                    "items": [_health(item) for item in health.items],
                },
                "history": {
                    "quality": history.quality.value,
                    "invalid_count": history.invalid_count,
                    "items": [
                        {
                            "dedupe_key": item.dedupe_key,
                            "action": _reading(item.action),
                            "observed_at": item.time.observed_at,
                            "received_at": item.time.received_at,
                        }
                        for item in history.items
                    ],
                },
                "evidence_sha256": {
                    "status": _fingerprint(status_response),
                    "health": _fingerprint(health_response),
                    "history": _fingerprint(history_response),
                },
            },
            metadata={
                "target_ref": self._target_ref,
                "history_page": self._history_page,
                "timestamp_basis": "collector_receipt",
                "raw_policy": "fingerprint_only_due_to_household_secrets",
            },
        )


def _health(item: LockHealth) -> dict[str, object]:
    return {
        "firmware_version": _reading(item.firmware_version),
        "battery_a": _reading(item.battery_a),
        "battery_b": _reading(item.battery_b),
        "hub_registered": _reading(item.hub_registered),
        "hub_firmware_version": _reading(item.hub_firmware_version),
        "operation_sound": _reading(item.operation_sound),
        "auto_lock_enabled": _reading(item.auto_lock_enabled),
        "auto_lock_sound": _reading(item.auto_lock_sound),
        "beacon_interval": _reading(item.beacon_interval),
    }


def _reading(reading: ObservedValue[object]) -> dict[str, object]:
    value = reading.value
    return {
        "value": value.value if isinstance(value, Enum) else value,
        "quality": reading.quality.value,
        "reason": reading.reason,
        "last_success_at": reading.last_success_at,
    }


def _fingerprint(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(canonical).hexdigest()
