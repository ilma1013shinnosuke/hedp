from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from hedp.adapters.switchbot.robot_state import normalize_robot_state


@dataclass(frozen=True)
class SwitchBotStatusProfile:
    """Device-family metadata for read-only status normalization.

    Profiles deliberately contain no commands.  Adding a new device family
    therefore cannot accidentally make it controllable.
    """

    name: str
    device_type_fragments: tuple[str, ...]
    fields: tuple[str, ...]
    expected_interval_seconds: int
    success_raw_policy: str = "anomaly_only"


COMMON_FIELDS = (
    "deviceId",
    "deviceType",
    "hubDeviceId",
    "version",
)

STATUS_PROFILES = (
    SwitchBotStatusProfile(
        "environment",
        ("meter", "woiosensor"),
        ("temperature", "humidity", "CO2", "battery"),
        3600,
    ),
    SwitchBotStatusProfile(
        "plug",
        ("plug",),
        (
            "power",
            "electricCurrent",
            "voltage",
            "weight",
            "electricityOfDay",
        ),
        3600,
    ),
    SwitchBotStatusProfile(
        "cleaner",
        ("k10", "s10", "s20", "robot vacuum"),
        (
            "battery",
            "onlineStatus",
            "workingStatus",
            "taskType",
            "waterBaseBattery",
        ),
        3600,
    ),
    SwitchBotStatusProfile(
        "light",
        ("strip light", "color bulb"),
        ("power", "brightness", "colorTemperature", "color"),
        3600,
    ),
    SwitchBotStatusProfile(
        "motion",
        ("motion sensor",),
        ("battery", "moveDetected", "brightness"),
        3600,
    ),
    SwitchBotStatusProfile(
        "presence",
        ("presence sensor",),
        (
            "battery",
            "moveDetected",
            "presenceState",
            "pirMotion",
            "brightness",
        ),
        3600,
    ),
)


def profile_for(device_type: str) -> SwitchBotStatusProfile | None:
    normalized = device_type.casefold()
    for profile in STATUS_PROFILES:
        if any(fragment in normalized for fragment in profile.device_type_fragments):
            return profile
    return None


def expected_interval_seconds(device_type: str) -> int:
    """Return the bounded polling interval declared by the read-only profile."""

    profile = profile_for(device_type)
    return profile.expected_interval_seconds if profile is not None else 3600


def success_raw_retention_reasons(
    device_type: str,
    body: Any,
    normalized: dict[str, Any],
) -> tuple[str, ...]:
    """Explain why a successful response still needs its Raw evidence.

    Known, normally parsed snapshots do not need a second JSON copy: their
    normalized observation is the success record.  Unknown or abnormal
    responses remain available for schema review and incident analysis.
    """

    profile = profile_for(device_type)
    reasons = []
    if profile is None:
        reasons.append("unknown_device_profile")
    elif profile.success_raw_policy == "always":
        reasons.append("profile_requires_raw")
    if not isinstance(body, dict):
        reasons.append("invalid_body_shape")
    elif not body:
        reasons.append("empty_body")
    if normalized["unknown_status_fields"]:
        reasons.append("unknown_status_fields")
    if normalized["unknown_status_values"]:
        reasons.append("unknown_status_values")
    if normalized["measurement_status"] != "observed":
        reasons.append("abnormal_measurement")
    return tuple(reasons)


def normalize_status(
    device: dict[str, Any],
    body: dict[str, Any],
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Normalize only fields whose meaning is established in the main schema.

    Unknown and not-yet-modelled fields are reported instead of silently being
    treated as supported.  The caller can retain the Raw response as evidence
    while a profile is reviewed and extended.
    """

    device_type = str(device.get("deviceType", ""))
    profile = profile_for(device_type)
    recognized = set(COMMON_FIELDS)
    if profile is not None:
        recognized.update(profile.fields)
    robot_state = (
        normalize_robot_state(body, observed_at=observed_at)
        if profile is not None and profile.name == "cleaner" and observed_at is not None
        else None
    )

    zero_unavailable = (
        profile is not None
        and profile.name == "environment"
        and all(body.get(key) == 0 for key in ("temperature", "humidity", "battery"))
        and all(key in body for key in ("temperature", "humidity", "battery"))
    )
    return {
        "status_profile": profile.name if profile else "unknown",
        "unknown_status_fields": tuple(sorted(set(body) - recognized)),
        "temperature_c": None if zero_unavailable else body.get("temperature"),
        "relative_humidity_percent": (
            None if zero_unavailable else body.get("humidity")
        ),
        "co2_ppm": body.get("CO2"),
        # Zero is meaningful for battery even when the measurements are absent.
        "battery_percent": body.get("battery"),
        "power_state": body.get("power"),
        "electric_current_ma": body.get("electricCurrent"),
        "voltage_v": body.get("voltage"),
        "power_consumed_daily_w": body.get("weight"),
        "usage_minutes_of_day": body.get("electricityOfDay"),
        "online_status": body.get("onlineStatus"),
        # Keep the established Raw vocabulary for backward compatibility.
        "working_status": body.get("workingStatus"),
        "robot_working_status": (
            robot_state.working_status.value if robot_state is not None else None
        ),
        "charging_status": (
            robot_state.charging_status.value if robot_state is not None else None
        ),
        "task_status": (
            robot_state.task_status.value
            if robot_state is not None
            else body.get("taskType")
        ),
        "water_base_battery_percent": (
            robot_state.water_base_battery_percent
            if robot_state is not None
            else body.get("waterBaseBattery")
        ),
        "status_quality": robot_state.quality.value
        if robot_state is not None
        else None,
        "unknown_status_values": (
            robot_state.unknown_values if robot_state is not None else ()
        ),
        "measurement_status": (
            "battery_depleted_or_unavailable" if zero_unavailable else "observed"
        ),
    }
