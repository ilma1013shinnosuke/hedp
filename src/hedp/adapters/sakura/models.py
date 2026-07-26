"""Privacy-safe, transport-independent Nissan Sakura read models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
import re
from typing import TypeVar

from hedp.observations import (
    ObservationTime,
    ObservedValue,
    Quality,
    require_aware_datetime,
)


_SAFE_REF = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_EnumValue = TypeVar("_EnumValue", bound=Enum)


class ChargingState(str, Enum):
    CHARGING = "charging"
    NOT_CHARGING = "not_charging"
    COMPLETE = "complete"


class PlugState(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"


class DoorLockState(str, Enum):
    LOCKED = "locked"
    UNLOCKED = "unlocked"


class ClimateState(str, Enum):
    ON = "on"
    OFF = "off"


@dataclass(frozen=True)
class SakuraVehicleState:
    """Requested vehicle facts with per-field absence and quality.

    No account, VIN, location, route, app session, or raw response is retained.
    """

    target_ref: str = field(repr=False)
    battery_percent: ObservedValue[int | float]
    estimated_range_km: ObservedValue[int | float]
    estimated_charge_completion_at: ObservedValue[str]
    charging: ObservedValue[ChargingState]
    plug: ObservedValue[PlugState]
    door_lock: ObservedValue[DoorLockState]
    cabin_temperature_c: ObservedValue[int | float]
    climate: ObservedValue[ClimateState]
    target_temperature_c: ObservedValue[int | float]
    alert_codes: ObservedValue[tuple[str, ...]]
    manufacturer_updated_at: ObservedValue[str]
    time: ObservationTime
    quality: Quality

    def __post_init__(self) -> None:
        if not isinstance(self.target_ref, str) or not _SAFE_REF.fullmatch(
            self.target_ref
        ):
            raise ValueError("target_ref must be a safe opaque reference")
        _validate_enum("charging", self.charging, ChargingState)
        _validate_enum("plug", self.plug, PlugState)
        _validate_enum("door_lock", self.door_lock, DoorLockState)
        _validate_enum("climate", self.climate, ClimateState)
        _validate_number("battery_percent", self.battery_percent, 0, 100)
        _validate_number("estimated_range_km", self.estimated_range_km, 0, None)
        _validate_number("cabin_temperature_c", self.cabin_temperature_c, None, None)
        _validate_number(
            "target_temperature_c",
            self.target_temperature_c,
            None,
            None,
        )
        if not isinstance(self.quality, Quality):
            raise TypeError("quality must be a Quality value")
        if not isinstance(self.time, ObservationTime):
            raise TypeError("time must be ObservationTime")
        _require_observed_value("alert_codes", self.alert_codes)
        if self.alert_codes.value is not None:
            if not isinstance(self.alert_codes.value, tuple):
                raise TypeError("alert_codes value must be a tuple")
            for value in self.alert_codes.value:
                if not isinstance(value, str) or not _SAFE_REF.fullmatch(value):
                    raise ValueError("alert_codes must contain safe opaque codes")
        for name in (
            "estimated_charge_completion_at",
            "manufacturer_updated_at",
        ):
            reading = getattr(self, name)
            _require_observed_value(name, reading)
            value = reading.value
            if value is not None:
                require_aware_datetime(name, value)


def _validate_number(
    name: str,
    reading: ObservedValue[int | float],
    minimum: int | float | None,
    maximum: int | float | None,
) -> None:
    _require_observed_value(name, reading)
    value = reading.value
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} value must be numeric")
    if not math.isfinite(value):
        raise ValueError(f"{name} value must be finite")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} value is below its physical bound")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} value is above its physical bound")


def _validate_enum(
    name: str,
    reading: ObservedValue[_EnumValue],
    expected_type: type[_EnumValue],
) -> None:
    _require_observed_value(name, reading)
    if reading.value is not None and not isinstance(reading.value, expected_type):
        raise TypeError(f"{name} value must be {expected_type.__name__}")


def _require_observed_value(name: str, value: object) -> None:
    if not isinstance(value, ObservedValue):
        raise TypeError(f"{name} must be ObservedValue")
