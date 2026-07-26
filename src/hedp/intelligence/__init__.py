"""Pure, read-only Layer 3 explanations."""

from .roof_snow import (
    RoofSnowEstimate,
    RoofSnowEvidence,
    RoofSnowState,
    RoofSnowThresholds,
    estimate_roof_snow,
)
from .solar_self_consumption_opportunity import (
    ExplanationOutcome,
    ExplanationReason,
    SolarSelfConsumptionExplanation,
    SolarSelfConsumptionOpportunityExplainer,
    explain_previous_day_solar_self_consumption_opportunity,
)

__all__ = [
    "ExplanationOutcome",
    "ExplanationReason",
    "RoofSnowEstimate",
    "RoofSnowEvidence",
    "RoofSnowState",
    "RoofSnowThresholds",
    "SolarSelfConsumptionExplanation",
    "SolarSelfConsumptionOpportunityExplainer",
    "estimate_roof_snow",
    "explain_previous_day_solar_self_consumption_opportunity",
]
