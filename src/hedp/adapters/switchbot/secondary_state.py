"""Typed, deviceType-independent state contracts for second-stage devices.

The four admitted families are selected by a local anonymous registration, not
by guessing a vendor ``deviceType`` string.  OpenAPI snapshots and future BLE
events share this normalization boundary.  Partial events contain only fields
that were actually reported; omitted event fields are not converted to
``missing`` observations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from hedp.observations import ObservedValue, Quality


_SAFE_ALIAS = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_RGB = re.compile(r"^(\d{1,3}):(\d{1,3}):(\d{1,3})$")
_COMMON_FIELDS = frozenset({"deviceId", "deviceType", "hubDeviceId", "version"})


class SecondaryDeviceKind(str, Enum):
    MOTION_SENSOR = "motion_sensor"
    PRESENCE_SENSOR_PRO = "presence_sensor_pro"
    E26_SMART_BULB = "e26_smart_bulb"
    STRIP_LIGHT_3 = "strip_light_3"


class RegistrationStatus(str, Enum):
    PENDING_REGISTRATION = "pending_registration"
    REGISTERED_UNVERIFIED = "registered_unverified"
    OBSERVABLE = "observable"


class SecondarySource(str, Enum):
    OPENAPI_SNAPSHOT = "openapi_snapshot"
    BLE_EVENT = "ble_event"


class SecondaryField(str, Enum):
    MOTION = "motion"
    PRESENCE = "presence"
    DETECTION_CONTINUES = "detection_continues"
    ILLUMINANCE = "illuminance"
    POWER = "power"
    BRIGHTNESS = "brightness"
    COLOR = "color"


class DetectionState(str, Enum):
    DETECTED = "detected"
    CLEAR = "clear"


class PresenceState(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"


class DetectionContinuation(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class IlluminanceState(str, Enum):
    BRIGHT = "bright"
    DIM = "dim"


class LightPower(str, Enum):
    ON = "on"
    OFF = "off"


@dataclass(frozen=True)
class RgbColor:
    red: int
    green: int
    blue: int

    def __post_init__(self) -> None:
        for name in ("red", "green", "blue"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if not 0 <= value <= 255:
                raise ValueError(f"{name} must be between 0 and 255")

    def canonical(self) -> str:
        return f"{self.red}:{self.green}:{self.blue}"


@dataclass(frozen=True)
class SecondaryDeviceRegistration:
    target_alias: str
    kind: SecondaryDeviceKind
    registration_status: RegistrationStatus
    vendor_device_id: str | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _require_alias(self.target_alias)
        if not isinstance(self.kind, SecondaryDeviceKind):
            raise TypeError("kind must be SecondaryDeviceKind")
        if not isinstance(self.registration_status, RegistrationStatus):
            raise TypeError("registration_status must be RegistrationStatus")
        if self.vendor_device_id is not None and (
            not isinstance(self.vendor_device_id, str)
            or not self.vendor_device_id.strip()
        ):
            raise ValueError("vendor_device_id must be a non-empty string or None")
        if (
            self.registration_status is RegistrationStatus.OBSERVABLE
            and self.vendor_device_id is None
        ):
            raise ValueError("observable registration requires vendor_device_id")


class SecondaryDeviceRegistry:
    """Resolve private vendor identifiers to safe aliases in memory only."""

    def __init__(
        self, registrations: tuple[SecondaryDeviceRegistration, ...] = ()
    ) -> None:
        aliases = [item.target_alias for item in registrations]
        if len(set(aliases)) != len(aliases):
            raise ValueError("secondary device aliases must be unique")
        vendor_ids = [
            item.vendor_device_id
            for item in registrations
            if item.vendor_device_id is not None
        ]
        if len(set(vendor_ids)) != len(vendor_ids):
            raise ValueError("secondary vendor device identifiers must be unique")
        self._registrations = registrations
        self._by_vendor_id = {
            item.vendor_device_id: item
            for item in registrations
            if item.vendor_device_id is not None
        }

    @property
    def registrations(self) -> tuple[SecondaryDeviceRegistration, ...]:
        return self._registrations

    def resolve_vendor_id(
        self, vendor_device_id: str
    ) -> SecondaryDeviceRegistration | None:
        return self._by_vendor_id.get(vendor_device_id)


@dataclass(frozen=True)
class SecondaryFieldObservation:
    field: SecondaryField
    observation: ObservedValue[
        DetectionState
        | PresenceState
        | DetectionContinuation
        | IlluminanceState
        | LightPower
        | int
        | RgbColor
    ]

    def to_dict(self) -> dict[str, object]:
        value = self.observation.value
        serialized: object
        if isinstance(value, Enum):
            serialized = value.value
        elif isinstance(value, RgbColor):
            serialized = value.canonical()
        else:
            serialized = value
        return {
            "field": self.field.value,
            "value": serialized,
            "quality": self.observation.quality.value,
            "reason": self.observation.reason,
        }


@dataclass(frozen=True)
class SecondaryDeviceObservation:
    target_alias: str
    kind: SecondaryDeviceKind
    registration_status: RegistrationStatus
    source: SecondarySource
    observed_at: datetime
    received_at: datetime
    fields: tuple[SecondaryFieldObservation, ...]
    quality: Quality
    reason: str | None = None
    unknown_fields: tuple[str, ...] = field(default=(), repr=False)

    def __post_init__(self) -> None:
        _require_alias(self.target_alias)
        _require_aware("observed_at", self.observed_at)
        _require_aware("received_at", self.received_at)
        if self.received_at.astimezone(timezone.utc) < self.observed_at.astimezone(
            timezone.utc
        ):
            raise ValueError("received_at must not be earlier than observed_at")
        if len({item.field for item in self.fields}) != len(self.fields):
            raise ValueError("secondary observation fields must be unique")
        if not isinstance(self.quality, Quality):
            raise TypeError("quality must be Quality")

    def field(self, name: SecondaryField) -> SecondaryFieldObservation | None:
        return next((item for item in self.fields if item.field is name), None)

    def to_storage_dict(self) -> dict[str, object]:
        return {
            "schema": "sumicore.switchbot.secondary-observation.v1",
            "target_alias": self.target_alias,
            "kind": self.kind.value,
            "registration_status": self.registration_status.value,
            "source": self.source.value,
            "observed_at": self.observed_at.isoformat(),
            "received_at": self.received_at.isoformat(),
            "quality": self.quality.value,
            "reason": self.reason,
            "fields": [item.to_dict() for item in self.fields],
            "unknown_fields": list(self.unknown_fields),
        }


_FIELD_KEYS = {
    SecondaryField.MOTION: "moveDetected",
    SecondaryField.PRESENCE: "presenceState",
    SecondaryField.DETECTION_CONTINUES: "pirMotion",
    SecondaryField.ILLUMINANCE: "brightness",
    SecondaryField.POWER: "power",
    SecondaryField.BRIGHTNESS: "brightness",
    SecondaryField.COLOR: "color",
}

_KIND_FIELDS = {
    SecondaryDeviceKind.MOTION_SENSOR: (
        SecondaryField.MOTION,
        SecondaryField.ILLUMINANCE,
    ),
    SecondaryDeviceKind.PRESENCE_SENSOR_PRO: (
        SecondaryField.MOTION,
        SecondaryField.PRESENCE,
        SecondaryField.DETECTION_CONTINUES,
        SecondaryField.ILLUMINANCE,
    ),
    SecondaryDeviceKind.E26_SMART_BULB: (
        SecondaryField.POWER,
        SecondaryField.BRIGHTNESS,
        SecondaryField.COLOR,
    ),
    SecondaryDeviceKind.STRIP_LIGHT_3: (
        SecondaryField.POWER,
        SecondaryField.BRIGHTNESS,
        SecondaryField.COLOR,
    ),
}


def expected_secondary_interval_seconds(kind: SecondaryDeviceKind) -> int:
    """Return an initial bounded snapshot interval, not a device event cadence."""

    if not isinstance(kind, SecondaryDeviceKind):
        raise TypeError("kind must be SecondaryDeviceKind")
    return 3600


def normalize_secondary_observation(
    registration: SecondaryDeviceRegistration,
    body: dict[str, Any] | None,
    *,
    source: SecondarySource,
    observed_at: datetime,
    received_at: datetime,
    evaluated_at: datetime,
    stale_after: timedelta,
) -> SecondaryDeviceObservation:
    """Normalize only evidence-backed fields for one explicitly registered kind."""

    for name, value in (
        ("observed_at", observed_at),
        ("received_at", received_at),
        ("evaluated_at", evaluated_at),
    ):
        _require_aware(name, value)
    if stale_after <= timedelta(0):
        raise ValueError("stale_after must be positive")
    if registration.registration_status is not RegistrationStatus.OBSERVABLE:
        return SecondaryDeviceObservation(
            registration.target_alias,
            registration.kind,
            registration.registration_status,
            source,
            observed_at,
            received_at,
            (),
            Quality.UNKNOWN,
            registration.registration_status.value,
        )
    if not isinstance(body, dict):
        return SecondaryDeviceObservation(
            registration.target_alias,
            registration.kind,
            registration.registration_status,
            source,
            observed_at,
            received_at,
            (),
            Quality.INVALID,
            "invalid_body_shape",
        )

    applicable = _KIND_FIELDS[registration.kind]
    reported = (
        applicable
        if source is SecondarySource.OPENAPI_SNAPSHOT
        else tuple(item for item in applicable if _FIELD_KEYS[item] in body)
    )
    stale = (
        evaluated_at.astimezone(timezone.utc)
        - observed_at.astimezone(timezone.utc)
        > stale_after
    )
    fields = tuple(
        SecondaryFieldObservation(
            item,
            _normalize_field(item, body, stale=stale),
        )
        for item in reported
    )
    known_raw_fields = _COMMON_FIELDS | {
        _FIELD_KEYS[item] for item in applicable
    }
    unknown_fields = tuple(sorted(set(body) - known_raw_fields))
    quality = _overall_quality(fields, unknown_fields)
    reason = (
        "no_fields_in_partial_event"
        if source is SecondarySource.BLE_EVENT and not fields
        else "unknown_fields"
        if unknown_fields
        else None
    )
    if reason == "no_fields_in_partial_event":
        quality = Quality.UNKNOWN
    return SecondaryDeviceObservation(
        registration.target_alias,
        registration.kind,
        registration.registration_status,
        source,
        observed_at,
        received_at,
        fields,
        quality,
        reason,
        unknown_fields,
    )


def secondary_raw_retention_reasons(
    observation: SecondaryDeviceObservation,
) -> tuple[str, ...]:
    reasons = []
    if observation.registration_status is not RegistrationStatus.OBSERVABLE:
        reasons.append(observation.registration_status.value)
    if observation.unknown_fields:
        reasons.append("unknown_status_fields")
    qualities = {item.observation.quality for item in observation.fields}
    if Quality.UNKNOWN in qualities:
        reasons.append("unknown_status_values")
    if Quality.INVALID in qualities:
        reasons.append("invalid_status_values")
    if Quality.MISSING in qualities:
        reasons.append("missing_status_fields")
    if observation.quality is Quality.INVALID and not observation.fields:
        reasons.append("invalid_body_shape")
    return tuple(reasons)


def _normalize_field(
    field_name: SecondaryField,
    body: dict[str, Any],
    *,
    stale: bool,
) -> ObservedValue[Any]:
    raw_key = _FIELD_KEYS[field_name]
    if raw_key not in body or body[raw_key] is None:
        return ObservedValue(None, Quality.MISSING, "field_not_reported")
    raw = body[raw_key]
    if field_name is SecondaryField.MOTION:
        result = _boolean_enum(raw, DetectionState.DETECTED, DetectionState.CLEAR)
    elif field_name is SecondaryField.PRESENCE:
        result = _boolean_enum(raw, PresenceState.PRESENT, PresenceState.ABSENT)
    elif field_name is SecondaryField.DETECTION_CONTINUES:
        result = _boolean_enum(
            raw,
            DetectionContinuation.ACTIVE,
            DetectionContinuation.INACTIVE,
        )
    elif field_name is SecondaryField.ILLUMINANCE:
        result = _string_enum(
            raw,
            {
                "bright": IlluminanceState.BRIGHT,
                "dim": IlluminanceState.DIM,
            },
        )
    elif field_name is SecondaryField.POWER:
        result = _string_enum(
            raw,
            {
                "on": LightPower.ON,
                "off": LightPower.OFF,
            },
        )
    elif field_name is SecondaryField.BRIGHTNESS:
        result = _bounded_integer(raw, minimum=0, maximum=100)
    else:
        result = _rgb(raw)
    if result.quality is Quality.GOOD and stale:
        return ObservedValue(result.value, Quality.STALE, "observation_stale")
    return result


def _boolean_enum(raw: Any, true_value: Enum, false_value: Enum) -> ObservedValue[Any]:
    if not isinstance(raw, bool):
        return ObservedValue(None, Quality.INVALID, "expected_boolean")
    return ObservedValue(true_value if raw else false_value, Quality.GOOD)


def _string_enum(raw: Any, values: dict[str, Enum]) -> ObservedValue[Any]:
    if not isinstance(raw, str):
        return ObservedValue(None, Quality.INVALID, "expected_string")
    value = values.get(raw.strip().casefold())
    if value is None:
        return ObservedValue(None, Quality.UNKNOWN, "unrecognized_value")
    return ObservedValue(value, Quality.GOOD)


def _bounded_integer(raw: Any, *, minimum: int, maximum: int) -> ObservedValue[int]:
    if isinstance(raw, bool) or not isinstance(raw, int):
        return ObservedValue(None, Quality.INVALID, "expected_integer")
    if not minimum <= raw <= maximum:
        return ObservedValue(None, Quality.INVALID, "value_out_of_range")
    return ObservedValue(raw, Quality.GOOD)


def _rgb(raw: Any) -> ObservedValue[RgbColor]:
    if not isinstance(raw, str):
        return ObservedValue(None, Quality.INVALID, "expected_rgb_string")
    match = _RGB.fullmatch(raw.strip())
    if match is None:
        return ObservedValue(None, Quality.UNKNOWN, "unrecognized_rgb_format")
    try:
        return ObservedValue(
            RgbColor(*(int(value) for value in match.groups())),
            Quality.GOOD,
        )
    except ValueError:
        return ObservedValue(None, Quality.INVALID, "rgb_out_of_range")


def _overall_quality(
    fields: tuple[SecondaryFieldObservation, ...],
    unknown_fields: tuple[str, ...],
) -> Quality:
    qualities = {item.observation.quality for item in fields}
    for quality in (
        Quality.INVALID,
        Quality.UNKNOWN,
        Quality.STALE,
        Quality.MISSING,
    ):
        if quality in qualities:
            return quality
    return Quality.UNKNOWN if unknown_fields else Quality.GOOD


def _require_alias(value: str) -> None:
    if not isinstance(value, str) or _SAFE_ALIAS.fullmatch(value) is None:
        raise ValueError("target_alias must be a safe opaque reference")


def _require_aware(name: str, value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
