"""Shared, domain-neutral observation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Generic, TypeVar


T = TypeVar("T")


class Quality(str, Enum):
    """How safely an observed or derived value can be used."""

    GOOD = "good"
    STALE = "stale"
    MISSING = "missing"
    INVALID = "invalid"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


def require_aware_datetime(name: str, value: str) -> datetime:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a UTC offset")
    return parsed


@dataclass(frozen=True)
class ObservationTime:
    """Source observation and SumiCore receipt times for one fact."""

    observed_at: str
    received_at: str

    def __post_init__(self) -> None:
        observed = require_aware_datetime("observed_at", self.observed_at)
        received = require_aware_datetime("received_at", self.received_at)
        if received < observed:
            raise ValueError("received_at must not be earlier than observed_at")


@dataclass(frozen=True)
class ObservedValue(Generic[T]):
    """One value with explicit absence/quality instead of a fake fallback."""

    value: T | None
    quality: Quality
    reason: str | None = None
    last_success_at: str | None = None

    def __post_init__(self) -> None:
        if self.quality in {Quality.MISSING, Quality.INVALID, Quality.UNKNOWN}:
            if self.value is not None:
                raise ValueError(f"{self.quality.value} value must be null")
        elif self.value is None:
            raise ValueError(f"{self.quality.value} value must not be null")
        if self.last_success_at is not None:
            require_aware_datetime("last_success_at", self.last_success_at)
