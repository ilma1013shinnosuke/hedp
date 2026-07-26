"""Privacy-safe Miele snapshot and finite SSE collection."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Callable

from hedp.observations import ObservationTime, ObservedValue
from hedp.storage import RawData

from .models import CollectionSource, MieleObservation
from .normalizer import normalize_observation, state_from_event
from .reader import MieleReader


class MieleReadOnlyCollector:
    """Collect allowlisted state without retaining device IDs or private text."""

    source = "miele_read_only"

    def __init__(
        self,
        reader: MieleReader,
        *,
        source_device_id: str,
        target_ref: str,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if not source_device_id:
            raise ValueError("source_device_id must not be empty")
        if not target_ref:
            raise ValueError("target_ref must not be empty")
        self._reader = reader
        self._source_device_id = source_device_id
        self._target_ref = target_ref
        self._clock = clock

    def collect_snapshot(self) -> RawData:
        response = self._reader.devices()
        device = _select_device(response, self._source_device_id)
        received_at = self._now()
        time = ObservationTime(received_at.isoformat(), received_at.isoformat())
        observation = normalize_observation(
            device,
            target_ref=self._target_ref,
            source=CollectionSource.REST,
            time=time,
        )
        return self._raw(
            received_at,
            "snapshot",
            [_observation(observation)],
            [_fingerprint(response)],
            input_count=1,
            discarded_count=0,
        )

    def collect_events(
        self,
        *,
        maximum_events: int = 64,
        timeout_seconds: float = 30.0,
    ) -> RawData:
        if not 1 <= maximum_events <= 1_024:
            raise ValueError("maximum_events must be between 1 and 1024")
        if not 0 < timeout_seconds <= 300:
            raise ValueError("timeout_seconds must be greater than 0 and at most 300")
        observations: list[dict[str, object]] = []
        fingerprints: list[str] = []
        seen: set[str] = set()
        input_count = 0
        discarded_count = 0
        last_received_at = self._now()
        for event in self._reader.events(
            self._source_device_id,
            maximum_events=maximum_events,
            timeout_seconds=timeout_seconds,
        ):
            input_count += 1
            last_received_at = self._now()
            state = state_from_event(
                event,
                source_device_id=self._source_device_id,
            )
            if state is None:
                discarded_count += 1
            else:
                time = ObservationTime(
                    last_received_at.isoformat(),
                    last_received_at.isoformat(),
                )
                normalized = _observation(
                    normalize_observation(
                        state,
                        target_ref=self._target_ref,
                        source=CollectionSource.SSE,
                        time=time,
                    )
                )
                state_key = _fingerprint(
                    {
                        key: value
                        for key, value in normalized.items()
                        if key not in {"source", "observed_at", "received_at"}
                    }
                )
                if state_key in seen:
                    discarded_count += 1
                else:
                    seen.add(state_key)
                    observations.append(normalized)
                    fingerprints.append(_fingerprint(event.payload))
            if input_count >= maximum_events:
                break
        return self._raw(
            last_received_at,
            "events",
            observations,
            fingerprints,
            input_count=input_count,
            discarded_count=discarded_count,
        )

    def _raw(
        self,
        received_at: datetime,
        collection_kind: str,
        observations: list[dict[str, object]],
        evidence_fingerprints: list[str],
        *,
        input_count: int,
        discarded_count: int,
    ) -> RawData:
        return RawData(
            source=self.source,
            timestamp=received_at,
            payload={
                "collection_kind": collection_kind,
                "observations": observations,
                "evidence_sha256": evidence_fingerprints,
                "input_count": input_count,
                "discarded_count": discarded_count,
            },
            metadata={
                "target_ref": self._target_ref,
                "timestamp_basis": "collector_receipt",
                "raw_policy": "fingerprint_only_due_to_household_secrets",
            },
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value


def _select_device(response: object, source_device_id: str) -> object:
    if not isinstance(response, dict):
        raise ValueError("Miele devices response must be an object")
    device = response.get(source_device_id)
    if not isinstance(device, dict):
        raise ValueError("configured Miele device is missing")
    return device


def _observation(value: MieleObservation) -> dict[str, object]:
    return {
        "source": value.source.value,
        "quality": value.quality.value,
        "observed_at": value.time.observed_at,
        "received_at": value.time.received_at,
        "status_code": _reading(value.status_code),
        "program_id": _reading(value.program_id),
        "program_type_code": _reading(value.program_type_code),
        "program_phase_code": _reading(value.program_phase_code),
        "remaining_minutes": _reading(value.remaining_minutes),
        "elapsed_minutes": _reading(value.elapsed_minutes),
        "scheduled_start_minutes_of_day": _reading(
            value.scheduled_start_minutes_of_day
        ),
        "temperature_c": _reading(value.temperature_c),
        "spin_speed_rpm": _reading(value.spin_speed_rpm),
        "drying_step_code": _reading(value.drying_step_code),
    }


def _reading(value: ObservedValue[object]) -> dict[str, object]:
    return {
        "value": value.value,
        "quality": value.quality.value,
        "reason": value.reason,
        "last_success_at": value.last_success_at,
    }


def _fingerprint(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(canonical).hexdigest()
