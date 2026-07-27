"""Bounded, privacy-safe BRAVIA read-only collection."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Callable, Mapping, Protocol

from hedp.storage import RawData

from .models import AudioOutput, NormalizedState
from .reader import ReadBatch, normalize_read_batch


class BraviaReadTransport(Protocol):
    """Read-only transport boundary; implementations must not expose write methods."""

    def power_status(self, *, timeout_seconds: float) -> Mapping[str, object]: ...

    def volume_information(
        self, *, timeout_seconds: float
    ) -> Mapping[str, object]: ...

    def playing_content_info(
        self, *, timeout_seconds: float
    ) -> Mapping[str, object]: ...


class BraviaReadOnlyCollector:
    """Perform exactly three bounded reads and retain only safe normalized state."""

    source = "bravia_read_only"

    def __init__(
        self,
        transport: BraviaReadTransport,
        *,
        target_ref: str,
        timeout_seconds: float = 5.0,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if not target_ref:
            raise ValueError("target_ref must not be empty")
        if not 0 < timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be greater than 0 and at most 30")
        self._transport = transport
        self._target_ref = target_ref
        self._timeout_seconds = timeout_seconds
        self._clock = clock

    def collect(self) -> RawData:
        observed_at = self._now()
        failures = 0
        responses: list[Mapping[str, object]] = []
        for read in (
            self._transport.power_status,
            self._transport.volume_information,
            self._transport.playing_content_info,
        ):
            try:
                response = read(timeout_seconds=self._timeout_seconds)
            except Exception:
                # Exception text can contain URLs, credentials, or household identifiers.
                response = {"error": [503]}
                failures += 1
            responses.append(response)

        received_at = self._now()
        state = normalize_read_batch(
            ReadBatch(
                power_response=responses[0],
                volume_response=responses[1],
                content_response=responses[2],
                observed_at=observed_at.isoformat(),
                received_at=received_at.isoformat(),
            )
        )
        return RawData(
            source=self.source,
            timestamp=received_at,
            payload={
                "state": _state(state),
                "evidence_sha256": [_fingerprint(value) for value in responses],
                "request_count": 3,
                "failure_count": failures,
            },
            metadata={
                "target_ref": self._target_ref,
                "timestamp_basis": "collector_request_and_receipt",
                "raw_policy": "fingerprint_only_due_to_household_secrets",
                "retry_count": 0,
            },
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value


def _state(value: NormalizedState) -> dict[str, object]:
    return {
        "power": {
            "value": value.power.value.value,
            "quality": value.power.quality.value,
            "reason": value.power.reason,
        },
        "audio": {
            "quality": value.audio.quality.value,
            "reason": value.audio.reason,
            "outputs": [_audio_output(item) for item in value.audio.outputs],
        },
        "content": {
            "source": value.content.source,
            "quality": value.content.quality.value,
            "reason": value.content.reason,
            "private_field_count": len(value.content.omitted_private_fields),
        },
        "observed_at": value.observed_at,
        "received_at": value.received_at,
    }


def _audio_output(value: AudioOutput) -> dict[str, object]:
    return {
        "target": value.target,
        "volume": value.volume,
        "muted": value.muted,
        "minimum": value.minimum,
        "maximum": value.maximum,
        "quality": value.quality.value,
        "reasons": list(value.reasons),
    }


def _fingerprint(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    return {"type": type(value).__name__}
