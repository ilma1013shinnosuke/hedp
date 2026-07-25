"""Pure, read-only Layer 3 explanations."""

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
    "SolarSelfConsumptionExplanation",
    "SolarSelfConsumptionOpportunityExplainer",
    "explain_previous_day_solar_self_consumption_opportunity",
]
