"""Privacy-safe Qrio read models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from hedp.observations import ObservationTime, ObservedValue, Quality


class LockPosition(str, Enum):
    LOCKED = "locked"
    UNLOCKED = "unlocked"


class LockAction(str, Enum):
    LOCKED = "locked"
    UNLOCKED = "unlocked"


class BatteryState(str, Enum):
    OK = "ok"
    LOW = "low"
    REPLACE = "replace"
    EMPTY = "empty"
    INVALID_VOLTAGE = "invalid_voltage"


@dataclass(frozen=True)
class LockStatus:
    target_ref: str = field(repr=False)
    position: ObservedValue[LockPosition]
    time: ObservationTime


@dataclass(frozen=True)
class LockHealth:
    target_ref: str = field(repr=False)
    firmware_version: ObservedValue[str]
    battery_a: ObservedValue[BatteryState]
    battery_b: ObservedValue[BatteryState]
    hub_registered: ObservedValue[bool]
    hub_firmware_version: ObservedValue[str]
    operation_sound: ObservedValue[bool]
    auto_lock_enabled: ObservedValue[bool]
    auto_lock_sound: ObservedValue[bool]
    beacon_interval: ObservedValue[int]
    time: ObservationTime


@dataclass(frozen=True)
class LockEvent:
    target_ref: str = field(repr=False)
    dedupe_key: str = field(repr=False)
    action: ObservedValue[LockAction]
    time: ObservationTime


@dataclass(frozen=True)
class LockHealthBatch:
    items: tuple[LockHealth, ...]
    quality: Quality
    time: ObservationTime
    invalid_count: int = 0
    unmapped_count: int = 0


@dataclass(frozen=True)
class LockEventBatch:
    items: tuple[LockEvent, ...]
    quality: Quality
    received_at: str
    invalid_count: int = 0
