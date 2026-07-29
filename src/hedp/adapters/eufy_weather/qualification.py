"""Privacy-minimized qualification helpers for offline and live snapshots."""

from __future__ import annotations

from enum import Enum
from typing import Any

from hedp.observations import ObservedValue

from .models import SunlightObservation


def qualification_report(
    observation: SunlightObservation,
    *,
    target_alias: str,
    source_mode: str,
) -> dict[str, Any]:
    """Return a JSON-safe report without a URL, device identifier, or image."""

    if source_mode not in {"fixture", "live_read_only"}:
        raise ValueError("source_mode must be fixture or live_read_only")
    status = (
        "pass_with_calibration_pending"
        if observation.quality.value == "good"
        and observation.state.reason == "site_calibration_required"
        else "pass"
        if observation.quality.value == "good"
        else "fail"
    )
    return {
        "schema_version": 1,
        "status": status,
        "source_mode": source_mode,
        "target_alias": target_alias,
        "observed_at": observation.time.observed_at,
        "received_at": observation.time.received_at,
        "attempt_count": observation.attempt_count,
        "overall_quality": observation.quality.value,
        "state": _observed_value(observation.state),
        "metrics": {
            "illumination_index": _observed_value(
                observation.illumination_index
            ),
            "shadow_contrast": _observed_value(observation.shadow_contrast),
            "clipped_fraction": _observed_value(observation.clipped_fraction),
        },
        "image_retained": False,
        "absolute_lux_claimed": False,
    }


def _observed_value(observation: ObservedValue[Any]) -> dict[str, Any]:
    value = observation.value
    if isinstance(value, Enum):
        value = value.value
    return {
        "value": value,
        "quality": observation.quality.value,
        "reason": observation.reason,
    }
