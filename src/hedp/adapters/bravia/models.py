from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .errors import ApiError


class Quality(str, Enum):
    GOOD = "good"
    STALE = "stale"
    MISSING = "missing"
    INVALID = "invalid"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class PowerState(str, Enum):
    ACTIVE = "active"
    STANDBY = "standby"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PowerReading:
    value: PowerState = PowerState.UNKNOWN
    quality: Quality = Quality.UNKNOWN
    reason: str | None = None
    raw_value: Any = None
    unknown: dict[str, Any] = field(default_factory=dict)
    error: ApiError | None = None


@dataclass(frozen=True)
class AudioOutput:
    target: str | None
    volume: int | None
    muted: bool | None
    minimum: int | None = None
    maximum: int | None = None
    quality: Quality = Quality.GOOD
    reasons: tuple[str, ...] = ()
    unknown: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AudioReading:
    outputs: tuple[AudioOutput, ...] = ()
    quality: Quality = Quality.UNKNOWN
    reason: str | None = None
    unknown: dict[str, Any] = field(default_factory=dict)
    error: ApiError | None = None


@dataclass(frozen=True)
class ContentState:
    """視聴内容・識別子を含まず、安全な入力種別だけを持つ現在状態。"""

    source: str | None = None
    quality: Quality = Quality.UNKNOWN
    reason: str | None = None
    omitted_private_fields: tuple[str, ...] = ()
    unknown: dict[str, Any] = field(default_factory=dict)
    error: ApiError | None = None


@dataclass(frozen=True)
class NormalizedState:
    power: PowerReading
    audio: AudioReading
    content: ContentState
    observed_at: str
    received_at: str
    unknown: dict[str, Any] = field(default_factory=dict)
