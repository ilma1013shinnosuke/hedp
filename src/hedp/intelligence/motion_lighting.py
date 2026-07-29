"""Layer 3 policy for motion-triggered lighting.

This module decides *what* lighting action is intended.  It does not call a
vendor API, sleep, persist data, or operate a device.  Layer 4 translates the
returned action into a Smart LEDZ command and verifies the result.
"""

from __future__ import annotations

import math
import re
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from hedp.adapters.switchbot.secondary_state import (
    DetectionState,
    RegistrationStatus,
    SecondaryDeviceKind,
    SecondaryDeviceObservation,
    SecondaryField,
)
from hedp.observations import Quality


_SAFE_ALIAS = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_MIN_HOLD_SECONDS = 1.0
_MAX_HOLD_SECONDS = 24 * 60 * 60
_SEEN_EVENT_LIMIT = 256


class LightingSelectionKind(str, Enum):
    """A user-configurable lighting selection, independent of vendor IDs."""

    SCENE = "scene"
    SCHEDULE = "schedule"


@dataclass(frozen=True)
class LightingSelection:
    """One intended scene or schedule selection for a lighting group."""

    kind: LightingSelectionKind
    target_alias: str
    selection_alias: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, LightingSelectionKind):
            raise TypeError("kind must be LightingSelectionKind")
        _require_alias("target_alias", self.target_alias)
        _require_alias("selection_alias", self.selection_alias)

    @property
    def capability(self) -> str:
        if self.kind is LightingSelectionKind.SCENE:
            return "scene_run"
        return "schedule_select"


@dataclass(frozen=True)
class MotionLightingRule:
    """Configurable behavior for one non-Pro motion sensor."""

    rule_alias: str
    sensor_alias: str
    hold_seconds: float
    on_detected: LightingSelection
    on_timeout: LightingSelection

    def __post_init__(self) -> None:
        _require_alias("rule_alias", self.rule_alias)
        _require_alias("sensor_alias", self.sensor_alias)
        if isinstance(self.hold_seconds, bool) or not isinstance(
            self.hold_seconds, (int, float)
        ):
            raise TypeError("hold_seconds must be a number")
        if not math.isfinite(self.hold_seconds):
            raise ValueError("hold_seconds must be finite")
        if not _MIN_HOLD_SECONDS <= self.hold_seconds <= _MAX_HOLD_SECONDS:
            raise ValueError("hold_seconds must be between 1 and 86400")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> MotionLightingRule:
        """Load a rule from a JSON-compatible mapping with strict keys."""

        allowed = {
            "schema",
            "rule_alias",
            "sensor_alias",
            "hold_seconds",
            "on_detected",
            "on_timeout",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"unknown motion lighting rule keys: {sorted(unknown)}")
        schema = payload.get("schema")
        if schema != "hestia.motion-lighting-rule.v1":
            raise ValueError("unsupported motion lighting rule schema")
        return cls(
            rule_alias=_require_string(payload, "rule_alias"),
            sensor_alias=_require_string(payload, "sensor_alias"),
            hold_seconds=_require_number(payload, "hold_seconds"),
            on_detected=_selection_from_mapping(payload, "on_detected"),
            on_timeout=_selection_from_mapping(payload, "on_timeout"),
        )


class MotionLightingReason(str, Enum):
    FIRST_DETECTION = "first_detection"
    HOLD_EXPIRED = "hold_expired"


@dataclass(frozen=True)
class MotionLightingDecision:
    """An action request emitted by Layer 3 for Layer 4 to inspect."""

    rule_alias: str
    selection: LightingSelection
    reason: MotionLightingReason
    event_id: str


class MotionLightingAutomation:
    """Deterministic, timer-injected state machine for a single rule."""

    def __init__(self, rule: MotionLightingRule) -> None:
        self._rule = rule
        self._deadline: float | None = None
        self._last_monotonic: float | None = None
        self._seen_event_ids: set[str] = set()
        self._seen_event_order: deque[str] = deque()
        self._sequence = 0

    @property
    def active(self) -> bool:
        return self._deadline is not None

    @property
    def deadline(self) -> float | None:
        return self._deadline

    def process(
        self,
        observation: SecondaryDeviceObservation,
        *,
        event_id: str,
        monotonic_seconds: float,
    ) -> tuple[MotionLightingDecision, ...]:
        """Accept a detection, act immediately once, and extend the deadline."""

        now = self._accept_time(monotonic_seconds)
        _require_event_id(event_id)
        if event_id in self._seen_event_ids:
            return ()
        self._remember_event(event_id)
        if not self._is_usable_detection(observation):
            return ()

        was_active = self.active
        self._deadline = now + self._rule.hold_seconds
        if was_active:
            return ()
        return (
            MotionLightingDecision(
                rule_alias=self._rule.rule_alias,
                selection=self._rule.on_detected,
                reason=MotionLightingReason.FIRST_DETECTION,
                event_id=event_id,
            ),
        )

    def tick(self, monotonic_seconds: float) -> tuple[MotionLightingDecision, ...]:
        """Emit the configured timeout action once after the last detection."""

        now = self._accept_time(monotonic_seconds)
        if self._deadline is None or now < self._deadline:
            return ()
        self._deadline = None
        self._sequence += 1
        return (
            MotionLightingDecision(
                rule_alias=self._rule.rule_alias,
                selection=self._rule.on_timeout,
                reason=MotionLightingReason.HOLD_EXPIRED,
                event_id=f"{self._rule.rule_alias}-timeout-{self._sequence}",
            ),
        )

    def manual_override(self) -> None:
        """Cancel the pending timeout so automation will not undo human action."""

        self._deadline = None

    def _is_usable_detection(
        self, observation: SecondaryDeviceObservation
    ) -> bool:
        if observation.target_alias != self._rule.sensor_alias:
            return False
        if observation.kind is not SecondaryDeviceKind.MOTION_SENSOR:
            return False
        if observation.registration_status is not RegistrationStatus.OBSERVABLE:
            return False
        if observation.quality is not Quality.GOOD:
            return False
        motion = observation.field(SecondaryField.MOTION)
        if motion is None or motion.observation.quality is not Quality.GOOD:
            return False
        return motion.observation.value is DetectionState.DETECTED

    def _accept_time(self, value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("monotonic_seconds must be a number")
        if not math.isfinite(value) or value < 0:
            raise ValueError("monotonic_seconds must be finite and non-negative")
        normalized = float(value)
        if self._last_monotonic is not None and normalized < self._last_monotonic:
            raise ValueError("monotonic_seconds must not move backwards")
        self._last_monotonic = normalized
        return normalized

    def _remember_event(self, event_id: str) -> None:
        self._seen_event_ids.add(event_id)
        self._seen_event_order.append(event_id)
        while len(self._seen_event_order) > _SEEN_EVENT_LIMIT:
            removed = self._seen_event_order.popleft()
            self._seen_event_ids.remove(removed)


def _selection_from_mapping(
    payload: Mapping[str, object], key: str
) -> LightingSelection:
    raw = payload.get(key)
    if not isinstance(raw, Mapping):
        raise TypeError(f"{key} must be an object")
    allowed = {"kind", "target_alias", "selection_alias"}
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"unknown {key} keys: {sorted(unknown)}")
    kind_value = _require_string(raw, "kind")
    try:
        kind = LightingSelectionKind(kind_value)
    except ValueError as exc:
        raise ValueError(f"{key}.kind must be scene or schedule") from exc
    return LightingSelection(
        kind=kind,
        target_alias=_require_string(raw, "target_alias"),
        selection_alias=_require_string(raw, "selection_alias"),
    )


def _require_alias(name: str, value: str) -> None:
    if not isinstance(value, str) or _SAFE_ALIAS.fullmatch(value) is None:
        raise ValueError(f"{name} must be a safe opaque alias")


def _require_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    return value


def _require_number(payload: Mapping[str, object], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{key} must be a number")
    return float(value)


def _require_event_id(value: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValueError("event_id must be a non-empty string of at most 256 characters")
