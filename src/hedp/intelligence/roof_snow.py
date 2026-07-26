"""Conservative, side-effect-free roof snow estimation.

The estimator combines already-collected weather and PV evidence.  It never
accesses a network, storage, or a device and cannot create an execution intent.
Optimizer data is optional and deliberately absent from the minimum contract.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from hedp.observations import Quality


class RoofSnowState(str, Enum):
    CLEAR = "clear"
    SNOW_POSSIBLE = "snow_possible"
    ACCUMULATING = "accumulating"
    COVERED = "covered"
    MELTING = "melting"
    RESIDUAL = "residual"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RoofSnowThresholds:
    minimum_expected_dc_kw: float = 0.5
    covered_power_ratio: float = 0.2
    melting_power_ratio: float = 0.35
    clear_power_ratio: float = 0.75
    snow_temperature_ceiling_c: float = 3.0
    material_snowfall_cm: float = 1.0

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite non-negative number")
        if not (
            self.covered_power_ratio
            < self.melting_power_ratio
            < self.clear_power_ratio
            <= 1
        ):
            raise ValueError("power ratio thresholds must be strictly increasing")


@dataclass(frozen=True)
class RoofSnowEvidence:
    observed_at: datetime
    daylight: bool
    actual_dc_power_kw: float | None
    expected_dc_power_kw: float | None
    ambient_temperature_c: float | None
    analysed_snow_depth_cm: float | None = None
    forecast_snowfall_cm: float | None = None
    previous_state: RoofSnowState = RoofSnowState.UNKNOWN
    quality: Quality = Quality.GOOD


@dataclass(frozen=True)
class RoofSnowEstimate:
    estimated_at: datetime
    state: RoofSnowState
    confidence: float
    reason_codes: tuple[str, ...]
    quality: Quality = Quality.ESTIMATED

    def safe_to_dict(self) -> dict[str, object]:
        return {
            "estimated_at": self.estimated_at.isoformat(),
            "state": self.state.value,
            "confidence": self.confidence,
            "reason_codes": list(self.reason_codes),
            "quality": self.quality.value,
        }


def estimate_roof_snow(
    evidence: RoofSnowEvidence,
    *,
    thresholds: RoofSnowThresholds = RoofSnowThresholds(),
) -> RoofSnowEstimate:
    """Estimate one bounded state without mistaking missing data for zero."""

    if evidence.observed_at.tzinfo is None or evidence.observed_at.utcoffset() is None:
        raise ValueError("observed_at must include a UTC offset")
    if evidence.quality not in {Quality.GOOD, Quality.ESTIMATED}:
        return _estimate(evidence, RoofSnowState.UNKNOWN, 0.0, "input_quality_unusable")

    values = (
        evidence.actual_dc_power_kw,
        evidence.expected_dc_power_kw,
        evidence.ambient_temperature_c,
        evidence.analysed_snow_depth_cm,
        evidence.forecast_snowfall_cm,
    )
    if any(value is not None and not math.isfinite(value) for value in values):
        return _estimate(evidence, RoofSnowState.UNKNOWN, 0.0, "input_nonfinite")
    if any(
        value is not None and value < 0
        for value in (
            evidence.actual_dc_power_kw,
            evidence.expected_dc_power_kw,
            evidence.analysed_snow_depth_cm,
            evidence.forecast_snowfall_cm,
        )
    ):
        return _estimate(evidence, RoofSnowState.UNKNOWN, 0.0, "input_out_of_range")

    snow_weather = (
        (evidence.analysed_snow_depth_cm or 0) >= thresholds.material_snowfall_cm
        or (evidence.forecast_snowfall_cm or 0) >= thresholds.material_snowfall_cm
    )
    cold_enough = (
        evidence.ambient_temperature_c is not None
        and evidence.ambient_temperature_c
        <= thresholds.snow_temperature_ceiling_c
    )

    ratio: float | None = None
    if (
        evidence.daylight
        and evidence.expected_dc_power_kw is not None
        and evidence.expected_dc_power_kw >= thresholds.minimum_expected_dc_kw
        and evidence.actual_dc_power_kw is not None
    ):
        ratio = evidence.actual_dc_power_kw / evidence.expected_dc_power_kw

    if ratio is not None and snow_weather and cold_enough:
        if ratio <= thresholds.covered_power_ratio:
            state = (
                RoofSnowState.ACCUMULATING
                if evidence.previous_state is RoofSnowState.SNOW_POSSIBLE
                else RoofSnowState.COVERED
            )
            return _estimate(
                evidence, state, 0.85, "snow_weather_and_severe_pv_suppression"
            )
        if (
            evidence.previous_state
            in {RoofSnowState.COVERED, RoofSnowState.ACCUMULATING}
            and ratio >= thresholds.melting_power_ratio
        ):
            return _estimate(
                evidence, RoofSnowState.MELTING, 0.75, "pv_recovery_after_cover"
            )

    if ratio is not None and evidence.previous_state is RoofSnowState.MELTING:
        if ratio < thresholds.clear_power_ratio:
            return _estimate(
                evidence, RoofSnowState.RESIDUAL, 0.65, "partial_pv_recovery"
            )
        return _estimate(evidence, RoofSnowState.CLEAR, 0.75, "pv_recovery_complete")

    if snow_weather and cold_enough:
        return _estimate(
            evidence, RoofSnowState.SNOW_POSSIBLE, 0.55, "snow_weather_only"
        )
    if (
        ratio is not None
        and ratio >= thresholds.clear_power_ratio
        and (evidence.analysed_snow_depth_cm or 0) == 0
    ):
        return _estimate(evidence, RoofSnowState.CLEAR, 0.7, "normal_pv_output")
    return _estimate(evidence, RoofSnowState.UNKNOWN, 0.0, "evidence_insufficient")


def _estimate(
    evidence: RoofSnowEvidence,
    state: RoofSnowState,
    confidence: float,
    *reason_codes: str,
) -> RoofSnowEstimate:
    return RoofSnowEstimate(
        estimated_at=evidence.observed_at,
        state=state,
        confidence=confidence,
        reason_codes=tuple(reason_codes),
    )
