"""Typed, evidence-preserving FusionSolar control-state normalization."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from hedp.observations import Quality


class BatteryMode(str, Enum):
    """Small canonical vocabulary for an observed battery flow mode."""

    CHARGING = "charging"
    DISCHARGING = "discharging"
    IDLE = "idle"
    STANDBY = "standby"
    UNKNOWN = "unknown"


class GenerationStatus(str, Enum):
    GENERATING = "generating"
    STOPPED = "stopped"
    UNKNOWN = "unknown"


_BATTERY_MODES = {
    "charge": BatteryMode.CHARGING,
    "charging": BatteryMode.CHARGING,
    "discharge": BatteryMode.DISCHARGING,
    "discharging": BatteryMode.DISCHARGING,
    "idle": BatteryMode.IDLE,
    "standby": BatteryMode.STANDBY,
}

_GENERATION_STATUSES = {
    "generating": GenerationStatus.GENERATING,
    "running": GenerationStatus.GENERATING,
    "stopped": GenerationStatus.STOPPED,
}


def normalize_battery_mode(value: object) -> BatteryMode:
    """Normalize only explicit labels; never infer mode from an unproven sign."""

    if isinstance(value, BatteryMode):
        return value
    if not isinstance(value, str):
        return BatteryMode.UNKNOWN
    return _BATTERY_MODES.get(value.strip().casefold(), BatteryMode.UNKNOWN)


def normalize_generation_status(value: object) -> GenerationStatus:
    if isinstance(value, GenerationStatus):
        return value
    if not isinstance(value, str):
        return GenerationStatus.UNKNOWN
    return _GENERATION_STATUSES.get(value.strip().casefold(), GenerationStatus.UNKNOWN)


@dataclass(frozen=True)
class FusionSolarControlState:
    """Sanitized state used for operation read-back.

    ``raw_battery_mode`` is optional evidence for an unknown display value.  It
    is deliberately excluded from ``repr`` so logs do not acquire vendor or
    household text accidentally.
    """

    generation_status: GenerationStatus
    battery_mode: BatteryMode
    observed_at: datetime
    raw_battery_mode: str | None = field(default=None, repr=False)
    generation_quality: Quality = Quality.GOOD
    battery_quality: Quality = Quality.GOOD

    def __post_init__(self) -> None:
        if not isinstance(self.generation_status, GenerationStatus):
            raise TypeError("generation_status must be GenerationStatus")
        if not isinstance(self.battery_mode, BatteryMode):
            raise TypeError("battery_mode must be BatteryMode")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.raw_battery_mode is not None and not isinstance(
            self.raw_battery_mode, str
        ):
            raise TypeError("raw_battery_mode must be a string or None")
        if not isinstance(self.generation_quality, Quality):
            raise TypeError("generation_quality must be Quality")
        if not isinstance(self.battery_quality, Quality):
            raise TypeError("battery_quality must be Quality")

    @classmethod
    def from_values(
        cls,
        *,
        generation_status: object,
        battery_mode: object,
        observed_at: datetime,
        generation_quality: Quality | None = None,
        battery_quality: Quality | None = None,
    ) -> "FusionSolarControlState":
        normalized_generation = normalize_generation_status(generation_status)
        normalized_battery = normalize_battery_mode(battery_mode)
        raw_mode = (
            battery_mode
            if isinstance(battery_mode, str)
            and normalized_battery is BatteryMode.UNKNOWN
            else None
        )
        return cls(
            normalized_generation,
            normalized_battery,
            observed_at,
            raw_mode,
            generation_quality
            or (
                Quality.UNKNOWN
                if normalized_generation is GenerationStatus.UNKNOWN
                else Quality.GOOD
            ),
            battery_quality
            or (
                Quality.UNKNOWN
                if normalized_battery is BatteryMode.UNKNOWN
                else Quality.GOOD
            ),
        )
