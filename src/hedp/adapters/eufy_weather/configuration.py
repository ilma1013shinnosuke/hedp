"""Validated, secret-free configuration for the Eufy weather adapter."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .acquisition_policy import EnergyAwareSnapshotPolicy
from .models import NormalizedRoi, SunlightCalibration


_ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_ENVIRONMENT_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
_FORBIDDEN_SECRET_KEYS = {
    "password",
    "rtsp_url",
    "secret",
    "stream_url",
    "token",
    "username",
}
_ALLOWED_ROOT_KEYS = {
    "analysis_width",
    "calibration",
    "energy_policy",
    "maximum_attempts",
    "shadow_roi",
    "sky_roi",
    "stream_url_env",
    "target_alias",
    "timeout_seconds",
}


@dataclass(frozen=True)
class EufyWeatherConfiguration:
    """Runtime-neutral settings; the RTSP value remains outside this object."""

    target_alias: str
    stream_url_env: str
    sky_roi: NormalizedRoi
    shadow_roi: NormalizedRoi
    calibration: SunlightCalibration | None = None
    analysis_width: int = 320
    timeout_seconds: float = 8.0
    maximum_attempts: int = 1
    energy_policy: EnergyAwareSnapshotPolicy = EnergyAwareSnapshotPolicy()

    def __post_init__(self) -> None:
        if not _ALIAS_PATTERN.fullmatch(self.target_alias):
            raise ValueError("target_alias must be a short anonymous identifier")
        if not _ENVIRONMENT_NAME_PATTERN.fullmatch(self.stream_url_env):
            raise ValueError("stream_url_env must be an uppercase environment name")
        if not 64 <= self.analysis_width <= 640:
            raise ValueError("analysis_width must be between 64 and 640")
        if not 0 < self.timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be greater than 0 and at most 30")
        if self.maximum_attempts not in {1, 2}:
            raise ValueError("maximum_attempts must be 1 or 2")


def load_eufy_weather_configuration(path: Path) -> EufyWeatherConfiguration:
    """Load a small JSON file which must not contain credential values."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("configuration root must be an object")
    return eufy_weather_configuration_from_mapping(payload)


def eufy_weather_configuration_from_mapping(
    payload: Mapping[str, Any],
) -> EufyWeatherConfiguration:
    """Parse configuration while rejecting common inline-secret fields."""

    forbidden = _find_forbidden_secret_keys(payload)
    if forbidden:
        raise ValueError("camera credentials and URLs must not be stored in configuration")
    unknown = set(payload) - _ALLOWED_ROOT_KEYS
    if unknown:
        raise ValueError("configuration contains unsupported fields")

    calibration_payload = payload.get("calibration")
    calibration = (
        None
        if calibration_payload is None
        else SunlightCalibration(**_require_mapping(calibration_payload, "calibration"))
    )
    policy_payload = _require_mapping(
        payload.get("energy_policy", {}),
        "energy_policy",
    )
    return EufyWeatherConfiguration(
        target_alias=_require_string(payload, "target_alias"),
        stream_url_env=_require_string(payload, "stream_url_env"),
        sky_roi=NormalizedRoi(
            **_require_mapping(payload.get("sky_roi"), "sky_roi")
        ),
        shadow_roi=NormalizedRoi(
            **_require_mapping(payload.get("shadow_roi"), "shadow_roi")
        ),
        calibration=calibration,
        analysis_width=int(payload.get("analysis_width", 320)),
        timeout_seconds=float(payload.get("timeout_seconds", 8.0)),
        maximum_attempts=int(payload.get("maximum_attempts", 1)),
        energy_policy=EnergyAwareSnapshotPolicy(**policy_payload),
    )


def _require_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return dict(value)


def _find_forbidden_secret_keys(value: Any) -> set[str]:
    """Inspect key names recursively without reading or reporting their values."""

    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized_key = str(key).lower()
            if normalized_key in _FORBIDDEN_SECRET_KEYS:
                found.add(normalized_key)
            found.update(_find_forbidden_secret_keys(nested))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.update(_find_forbidden_secret_keys(item))
    return found
