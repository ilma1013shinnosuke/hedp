"""Energy-aware policy for deciding whether a camera snapshot is worthwhile.

The policy receives already-normalized energy evidence.  It does not read a
solar inverter, contact a camera, sleep, schedule work, or persist state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from hedp.observations import ObservedValue, Quality, require_aware_datetime


class SnapshotAction(str, Enum):
    """What the scheduler should do with the next weather snapshot."""

    ACQUIRE = "acquire"
    SKIP_HIGH_GENERATION = "skip_high_generation"
    PAUSE_ENERGY_SCARCITY = "pause_energy_scarcity"


@dataclass(frozen=True)
class EnergyEvidence:
    """Privacy-minimized energy facts supplied by another Adapter."""

    observed_at: str
    rolling_generation_kw: ObservedValue[float]
    generation_window_minutes: int
    rated_ac_kw: float
    battery_soc_percent: ObservedValue[float] | None = None
    forecast_remaining_generation_kwh: ObservedValue[float] | None = None
    forecast_remaining_essential_load_kwh: ObservedValue[float] | None = None

    def __post_init__(self) -> None:
        require_aware_datetime("observed_at", self.observed_at)
        if self.generation_window_minutes <= 0:
            raise ValueError("generation_window_minutes must be greater than zero")
        if self.rated_ac_kw <= 0:
            raise ValueError("rated_ac_kw must be greater than zero")
        _require_non_negative(self.rolling_generation_kw, "rolling_generation_kw")
        if self.battery_soc_percent is not None:
            _require_range(
                self.battery_soc_percent,
                "battery_soc_percent",
                minimum=0,
                maximum=100,
            )
        if self.forecast_remaining_generation_kwh is not None:
            _require_non_negative(
                self.forecast_remaining_generation_kwh,
                "forecast_remaining_generation_kwh",
            )
        if self.forecast_remaining_essential_load_kwh is not None:
            _require_non_negative(
                self.forecast_remaining_essential_load_kwh,
                "forecast_remaining_essential_load_kwh",
            )


@dataclass(frozen=True)
class EnergyAwareSnapshotPolicy:
    """Configurable thresholds; defaults are conservative starting values."""

    high_generation_ratio: float = 0.70
    high_generation_min_window_minutes: int = 10
    evidence_max_age_seconds: int = 120
    winter_months: tuple[int, ...] = (11, 12, 1, 2, 3)
    pause_battery_soc_percent: float = 30
    resume_battery_soc_percent: float = 40
    pause_energy_deficit_kwh: float = 2
    resume_energy_surplus_kwh: float = 2
    normal_interval_minutes: int = 10
    uncertain_interval_minutes: int = 60
    paused_recheck_minutes: int = 60

    def __post_init__(self) -> None:
        if not 0 < self.high_generation_ratio <= 1:
            raise ValueError("high_generation_ratio must be greater than 0 and at most 1")
        if self.high_generation_min_window_minutes <= 0:
            raise ValueError(
                "high_generation_min_window_minutes must be greater than zero"
            )
        if self.evidence_max_age_seconds <= 0:
            raise ValueError("evidence_max_age_seconds must be greater than zero")
        if not self.winter_months or any(
            month < 1 or month > 12 for month in self.winter_months
        ):
            raise ValueError("winter_months must contain months from 1 to 12")
        if not 0 <= self.pause_battery_soc_percent < self.resume_battery_soc_percent <= 100:
            raise ValueError("battery pause threshold must be below resume threshold")
        if self.pause_energy_deficit_kwh < 0 or self.resume_energy_surplus_kwh < 0:
            raise ValueError("energy margins must not be negative")
        if min(
            self.normal_interval_minutes,
            self.uncertain_interval_minutes,
            self.paused_recheck_minutes,
        ) <= 0:
            raise ValueError("intervals must be greater than zero")


@dataclass(frozen=True)
class SnapshotDecision:
    """One auditable decision without household identifiers."""

    action: SnapshotAction
    reason: str
    next_evaluation_minutes: int
    evidence_quality: Quality


def decide_snapshot_acquisition(
    evidence: EnergyEvidence,
    *,
    policy: EnergyAwareSnapshotPolicy = EnergyAwareSnapshotPolicy(),
    now: datetime,
    previously_paused: bool = False,
) -> SnapshotDecision:
    """Choose whether to acquire one frame without causing external effects."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    observed_at = require_aware_datetime("observed_at", evidence.observed_at)
    age_seconds = (now - observed_at).total_seconds()
    generation_trusted = (
        0 <= age_seconds <= policy.evidence_max_age_seconds
        and evidence.rolling_generation_kw.quality == Quality.GOOD
        and evidence.rolling_generation_kw.value is not None
        and evidence.generation_window_minutes
        >= policy.high_generation_min_window_minutes
    )

    if generation_trusted:
        generation_ratio = (
            evidence.rolling_generation_kw.value / evidence.rated_ac_kw
        )
        if generation_ratio >= policy.high_generation_ratio:
            return SnapshotDecision(
                action=SnapshotAction.SKIP_HIGH_GENERATION,
                reason="sustained_generation_already_conclusive",
                next_evaluation_minutes=policy.normal_interval_minutes,
                evidence_quality=Quality.GOOD,
            )

    is_winter = now.month in policy.winter_months
    scarcity = _scarcity_reason(evidence, policy) if is_winter else None
    if scarcity is not None:
        scarcity_reason, scarcity_quality = scarcity
        return SnapshotDecision(
            action=SnapshotAction.PAUSE_ENERGY_SCARCITY,
            reason=scarcity_reason,
            next_evaluation_minutes=policy.paused_recheck_minutes,
            evidence_quality=scarcity_quality,
        )

    if previously_paused and is_winter and not _has_recovery_evidence(evidence, policy):
        return SnapshotDecision(
            action=SnapshotAction.PAUSE_ENERGY_SCARCITY,
            reason="recovery_hysteresis_not_satisfied",
            next_evaluation_minutes=policy.paused_recheck_minutes,
            evidence_quality=Quality.UNKNOWN,
        )

    if not generation_trusted:
        return SnapshotDecision(
            action=SnapshotAction.ACQUIRE,
            reason="energy_evidence_incomplete_use_low_frequency",
            next_evaluation_minutes=policy.uncertain_interval_minutes,
            evidence_quality=Quality.UNKNOWN,
        )

    return SnapshotDecision(
        action=SnapshotAction.ACQUIRE,
        reason="snapshot_evidence_still_useful",
        next_evaluation_minutes=policy.normal_interval_minutes,
        evidence_quality=Quality.GOOD,
    )


def _scarcity_reason(
    evidence: EnergyEvidence, policy: EnergyAwareSnapshotPolicy
) -> tuple[str, Quality] | None:
    battery_observation = evidence.battery_soc_percent
    battery_soc = _usable_value(battery_observation)
    if (
        battery_soc is not None
        and battery_soc <= policy.pause_battery_soc_percent
    ):
        assert battery_observation is not None
        return "winter_battery_reserve_low", battery_observation.quality

    balance, balance_quality = _forecast_energy_balance(evidence)
    if balance is not None and balance <= -policy.pause_energy_deficit_kwh:
        assert balance_quality is not None
        return "winter_forecast_energy_deficit", balance_quality
    return None


def _has_recovery_evidence(
    evidence: EnergyEvidence, policy: EnergyAwareSnapshotPolicy
) -> bool:
    battery_soc = _usable_value(evidence.battery_soc_percent)
    balance, _ = _forecast_energy_balance(evidence)
    battery_recovered = (
        battery_soc is not None
        and battery_soc >= policy.resume_battery_soc_percent
    )
    forecast_recovered = (
        balance is not None and balance >= policy.resume_energy_surplus_kwh
    )
    if battery_soc is not None and not battery_recovered:
        return False
    if balance is not None and not forecast_recovered:
        return False
    return battery_recovered or forecast_recovered


def _forecast_energy_balance(
    evidence: EnergyEvidence,
) -> tuple[float | None, Quality | None]:
    generation_observation = evidence.forecast_remaining_generation_kwh
    load_observation = evidence.forecast_remaining_essential_load_kwh
    generation = _usable_value(generation_observation)
    load = _usable_value(load_observation)
    if generation is None or load is None:
        return None, None
    assert generation_observation is not None
    assert load_observation is not None
    quality = (
        Quality.ESTIMATED
        if Quality.ESTIMATED
        in {generation_observation.quality, load_observation.quality}
        else Quality.GOOD
    )
    return generation - load, quality


def _usable_value(observation: ObservedValue[float] | None) -> float | None:
    if observation is None or observation.quality not in {
        Quality.GOOD,
        Quality.ESTIMATED,
    }:
        return None
    return observation.value


def _require_non_negative(observation: ObservedValue[float], name: str) -> None:
    if observation.value is not None and observation.value < 0:
        raise ValueError(f"{name} must not be negative")


def _require_range(
    observation: ObservedValue[float],
    name: str,
    *,
    minimum: float,
    maximum: float,
) -> None:
    if observation.value is not None and not minimum <= observation.value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
