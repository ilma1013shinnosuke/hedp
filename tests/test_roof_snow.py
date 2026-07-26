from datetime import datetime, timezone

import pytest

from hedp.intelligence.roof_snow import (
    RoofSnowEvidence,
    RoofSnowState,
    RoofSnowThresholds,
    estimate_roof_snow,
)
from hedp.observations import Quality


NOW = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)


def evidence(**changes):
    values = {
        "observed_at": NOW,
        "daylight": True,
        "actual_dc_power_kw": 0.3,
        "expected_dc_power_kw": 3.0,
        "ambient_temperature_c": -1.0,
        "analysed_snow_depth_cm": 10.0,
    }
    values.update(changes)
    return RoofSnowEvidence(**values)


def test_weather_and_severe_pv_suppression_estimates_cover():
    result = estimate_roof_snow(evidence())
    assert result.state is RoofSnowState.COVERED
    assert result.confidence == 0.85
    assert result.quality is Quality.ESTIMATED


def test_weather_alone_is_only_possible_not_covered():
    result = estimate_roof_snow(
        evidence(daylight=False, actual_dc_power_kw=None, expected_dc_power_kw=None)
    )
    assert result.state is RoofSnowState.SNOW_POSSIBLE
    assert result.confidence < 0.6


def test_night_zero_power_is_not_snow_evidence():
    result = estimate_roof_snow(
        evidence(
            daylight=False,
            actual_dc_power_kw=0.0,
            expected_dc_power_kw=0.0,
            analysed_snow_depth_cm=0.0,
            forecast_snowfall_cm=0.0,
        )
    )
    assert result.state is RoofSnowState.UNKNOWN


def test_recovery_after_cover_estimates_melting():
    result = estimate_roof_snow(
        evidence(
            actual_dc_power_kw=1.5,
            previous_state=RoofSnowState.COVERED,
        )
    )
    assert result.state is RoofSnowState.MELTING


def test_full_recovery_after_melting_estimates_clear():
    result = estimate_roof_snow(
        evidence(
            actual_dc_power_kw=2.7,
            analysed_snow_depth_cm=0.0,
            forecast_snowfall_cm=0.0,
            previous_state=RoofSnowState.MELTING,
        )
    )
    assert result.state is RoofSnowState.CLEAR


@pytest.mark.parametrize("quality", [Quality.STALE, Quality.MISSING, Quality.INVALID])
def test_unusable_quality_never_produces_a_snow_claim(quality):
    result = estimate_roof_snow(evidence(quality=quality))
    assert result.state is RoofSnowState.UNKNOWN
    assert result.confidence == 0.0


def test_nonfinite_and_negative_inputs_are_unknown():
    assert (
        estimate_roof_snow(evidence(actual_dc_power_kw=float("nan"))).state
        is RoofSnowState.UNKNOWN
    )
    assert (
        estimate_roof_snow(evidence(analysed_snow_depth_cm=-1)).state
        is RoofSnowState.UNKNOWN
    )


def test_threshold_order_is_validated():
    with pytest.raises(ValueError):
        RoofSnowThresholds(
            covered_power_ratio=0.5,
            melting_power_ratio=0.4,
        )


def test_timestamp_must_include_offset():
    with pytest.raises(ValueError):
        estimate_roof_snow(evidence(observed_at=datetime(2026, 1, 1)))
