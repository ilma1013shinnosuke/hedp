"""Finite, privacy-safe handling for unverified Smart LEDZ notifications."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
import math
import re


_SAFE_NOTIFICATION_FIELDS = frozenset(
    {
        "event",
        "status",
        "timestamp",
        "type",
    }
)
_SENSITIVE_PARTS = frozenset(
    {
        "address",
        "auth",
        "config",
        "id",
        "ip",
        "mac",
        "name",
        "password",
        "secret",
        "serial",
        "setting",
        "ssid",
        "token",
        "udn",
    }
)


class NotificationDisposition(str, Enum):
    NEW_UNSUPPORTED = "new_unsupported"
    DUPLICATE = "duplicate"
    INVALID = "invalid"


@dataclass(frozen=True)
class NormalizedNotification:
    disposition: NotificationDisposition
    fingerprint: str | None
    safe_fields: tuple[str, ...]
    redacted_field_count: int
    resync_required: bool
    reason: str


class SmartLedzNotificationNormalizer:
    """Normalize only notification envelopes, never guessed event semantics.

    Dedupe memory is strictly bounded.  Every new or invalid notification
    requires a read-only resync because no anonymous payload fixture currently
    proves which device state changed.  A successful external resync clears
    that flag but does not replay or reinterpret retained notifications.
    """

    def __init__(
        self,
        *,
        maximum_fingerprints: int = 256,
        maximum_payload_bytes: int = 64 * 1024,
        maximum_depth: int = 16,
        maximum_fields: int = 256,
    ) -> None:
        if isinstance(maximum_fingerprints, bool) or not isinstance(
            maximum_fingerprints, int
        ):
            raise TypeError("maximum_fingerprints must be an integer")
        if not 1 <= maximum_fingerprints <= 4096:
            raise ValueError("maximum_fingerprints must be between 1 and 4096")
        _bounded_integer(
            "maximum_payload_bytes",
            maximum_payload_bytes,
            minimum=256,
            maximum=1024 * 1024,
        )
        _bounded_integer(
            "maximum_depth",
            maximum_depth,
            minimum=1,
            maximum=64,
        )
        _bounded_integer(
            "maximum_fields",
            maximum_fields,
            minimum=1,
            maximum=4096,
        )
        self._maximum = maximum_fingerprints
        self._maximum_payload_bytes = maximum_payload_bytes
        self._maximum_depth = maximum_depth
        self._maximum_fields = maximum_fields
        self._order: deque[str] = deque()
        self._seen: set[str] = set()
        self._resync_required = True

    @property
    def resync_required(self) -> bool:
        return self._resync_required

    @property
    def retained_fingerprint_count(self) -> int:
        return len(self._order)

    def mark_resynchronized(self) -> None:
        self._resync_required = False

    def normalize(self, payload: object) -> NormalizedNotification:
        if not isinstance(payload, Mapping):
            return self._invalid("notification_not_object")
        structural_error = _bounded_json_structure(
            payload,
            maximum_payload_bytes=self._maximum_payload_bytes,
            maximum_depth=self._maximum_depth,
            maximum_fields=self._maximum_fields,
        )
        if structural_error is not None:
            return self._invalid(structural_error)
        try:
            canonical = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError):
            return self._invalid("notification_not_json")
        if len(canonical) > self._maximum_payload_bytes:
            return self._invalid("notification_byte_limit_exceeded")
        fingerprint = sha256(canonical).hexdigest()
        safe_fields, redacted_count = _safe_fields(payload)
        if fingerprint in self._seen:
            return NormalizedNotification(
                NotificationDisposition.DUPLICATE,
                fingerprint,
                safe_fields,
                redacted_count,
                self._resync_required,
                "duplicate_notification",
            )
        self._remember(fingerprint)
        self._resync_required = True
        return NormalizedNotification(
            NotificationDisposition.NEW_UNSUPPORTED,
            fingerprint,
            safe_fields,
            redacted_count,
            True,
            "notification_schema_unverified",
        )

    def _invalid(self, reason: str) -> NormalizedNotification:
        self._resync_required = True
        return NormalizedNotification(
            NotificationDisposition.INVALID,
            None,
            (),
            0,
            True,
            reason,
        )

    def _remember(self, fingerprint: str) -> None:
        if len(self._order) == self._maximum:
            evicted = self._order.popleft()
            self._seen.remove(evicted)
        self._order.append(fingerprint)
        self._seen.add(fingerprint)


def _safe_fields(payload: Mapping[object, object]) -> tuple[tuple[str, ...], int]:
    safe: list[str] = []
    redacted = 0
    for key in payload:
        if (
            not isinstance(key, str)
            or key not in _SAFE_NOTIFICATION_FIELDS
            or _sensitive(key)
        ):
            redacted += 1
        else:
            safe.append(key)
    return tuple(sorted(safe)), redacted


def _sensitive(value: str) -> bool:
    with_boundaries = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
    normalized = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", with_boundaries).casefold()
    parts = tuple(part for part in normalized.replace("-", "_").split("_") if part)
    return bool(_SENSITIVE_PARTS.intersection(parts))


def _bounded_integer(
    name: str,
    value: int,
    *,
    minimum: int,
    maximum: int,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")


def _bounded_json_structure(
    value: object,
    *,
    maximum_payload_bytes: int,
    maximum_depth: int,
    maximum_fields: int,
) -> str | None:
    """Reject unsafe structures before creating a serialized payload copy."""

    stack: list[tuple[object, int]] = [(value, 0)]
    active_containers: set[int] = set()
    field_count = 0
    estimated_bytes = 0
    while stack:
        current, depth = stack.pop()
        if depth > maximum_depth:
            return "notification_depth_limit_exceeded"
        if isinstance(current, Mapping):
            identity = id(current)
            if identity in active_containers:
                return "notification_not_json"
            active_containers.add(identity)
            field_count += len(current)
            if field_count > maximum_fields:
                return "notification_field_limit_exceeded"
            stack.append((_ContainerExit(identity), depth))
            for key, nested in current.items():
                if not isinstance(key, str):
                    return "notification_not_json"
                estimated_bytes += len(key.encode("utf-8")) + 4
                if estimated_bytes > maximum_payload_bytes:
                    return "notification_byte_limit_exceeded"
                stack.append((nested, depth + 1))
            continue
        if isinstance(current, (list, tuple)):
            identity = id(current)
            if identity in active_containers:
                return "notification_not_json"
            active_containers.add(identity)
            field_count += len(current)
            if field_count > maximum_fields:
                return "notification_field_limit_exceeded"
            stack.append((_ContainerExit(identity), depth))
            stack.extend((nested, depth + 1) for nested in current)
            continue
        if isinstance(current, _ContainerExit):
            active_containers.discard(current.identity)
            continue
        if current is None or isinstance(current, bool):
            estimated_bytes += 5
        elif isinstance(current, str):
            estimated_bytes += len(current.encode("utf-8")) + 2
        elif isinstance(current, int):
            estimated_bytes += len(str(current))
        elif isinstance(current, float):
            if not math.isfinite(current):
                return "notification_not_json"
            estimated_bytes += len(repr(current))
        else:
            return "notification_not_json"
        if estimated_bytes > maximum_payload_bytes:
            return "notification_byte_limit_exceeded"
    return None


@dataclass(frozen=True)
class _ContainerExit:
    identity: int
