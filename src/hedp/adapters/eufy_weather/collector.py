"""Bounded orchestration for one privacy-minimized camera observation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .acquisition_policy import (
    EnergyAwareSnapshotPolicy,
    EnergyEvidence,
    SnapshotAction,
    SnapshotDecision,
    decide_snapshot_acquisition,
)
from .analysis import analyze_sunlight, unavailable_observation
from .errors import SnapshotError
from .models import (
    NormalizedRoi,
    SunlightCalibration,
    SunlightObservation,
)
from .reader import SnapshotReader


@dataclass(frozen=True)
class EnergyGatedCollectionResult:
    """One scheduler decision and an optional camera observation.

    A skipped or paused decision deliberately has no fabricated camera
    observation.  The decision itself is the auditable evidence that the
    camera was not contacted.
    """

    decision: SnapshotDecision
    observation: SunlightObservation | None

    def __post_init__(self) -> None:
        should_have_observation = self.decision.action == SnapshotAction.ACQUIRE
        if should_have_observation != (self.observation is not None):
            raise ValueError("observation presence must match the acquisition decision")


class EufyWeatherCollector:
    """Acquire one snapshot, derive evidence, then discard the image."""

    def __init__(
        self,
        reader: SnapshotReader,
        *,
        target_ref: str,
        sky_roi: NormalizedRoi,
        shadow_roi: NormalizedRoi,
        calibration: SunlightCalibration | None = None,
        timeout_seconds: float = 8.0,
        maximum_attempts: int = 1,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if not target_ref:
            raise ValueError("target_ref must not be empty")
        if not 0 < timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be greater than 0 and at most 30")
        if maximum_attempts not in {1, 2}:
            raise ValueError("maximum_attempts must be 1 or 2")
        self._reader = reader
        self._target_ref = target_ref
        self._sky_roi = sky_roi
        self._shadow_roi = shadow_roi
        self._calibration = calibration
        self._timeout_seconds = timeout_seconds
        self._maximum_attempts = maximum_attempts
        self._clock = clock

    def collect(self) -> SunlightObservation:
        started_at = self._now()
        failure_reason = "snapshot_unavailable"
        for attempt in range(1, self._maximum_attempts + 1):
            try:
                frame = self._reader.read_snapshot(
                    timeout_seconds=self._timeout_seconds
                )
            except SnapshotError as exc:
                failure_reason = exc.code
                if not exc.retryable:
                    break
            except Exception:
                # Upstream messages may contain credentials, URLs, or identifiers.
                failure_reason = "snapshot_unexpected_error"
                break
            else:
                return analyze_sunlight(
                    frame,
                    target_ref=self._target_ref,
                    sky_roi=self._sky_roi,
                    shadow_roi=self._shadow_roi,
                    calibration=self._calibration,
                    attempt_count=attempt,
                    clock=self._clock,
                )

        finished_at = self._now()
        return unavailable_observation(
            target_ref=self._target_ref,
            observed_at=started_at.isoformat(),
            received_at=finished_at.isoformat(),
            attempt_count=attempt,
            reason=failure_reason,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value


def collect_if_energy_allows(
    collector: EufyWeatherCollector,
    evidence: EnergyEvidence,
    *,
    now: datetime,
    policy: EnergyAwareSnapshotPolicy = EnergyAwareSnapshotPolicy(),
    previously_paused: bool = False,
) -> EnergyGatedCollectionResult:
    """Evaluate normalized energy evidence before contacting the camera."""

    decision = decide_snapshot_acquisition(
        evidence,
        policy=policy,
        now=now,
        previously_paused=previously_paused,
    )
    observation = (
        collector.collect()
        if decision.action == SnapshotAction.ACQUIRE
        else None
    )
    return EnergyGatedCollectionResult(
        decision=decision,
        observation=observation,
    )
