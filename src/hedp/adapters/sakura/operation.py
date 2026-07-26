"""Capability-gated dry-run operation contracts for Nissan Sakura.

There is deliberately no app automation, private API, network transport,
credential handling, or live dispatch path.  Remote unlock is absent from the
operation enum and explicitly rejected by the helper below.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import math
import re
from typing import TypeAlias


_SAFE_REF = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
UNSUPPORTED_OPERATION_NAMES = frozenset({"unlock"})


class SakuraCapability(str, Enum):
    CHARGE = "charge"
    CLIMATE = "climate"
    TEMPERATURE = "temperature"
    LOCK = "lock"


class SakuraOperation(str, Enum):
    START_CHARGING = "start_charging"
    START_CLIMATE = "start_climate"
    STOP_CLIMATE = "stop_climate"
    SET_CABIN_TEMPERATURE = "set_cabin_temperature"
    LOCK = "lock"


class SakuraDryRunOutcome(str, Enum):
    WOULD_DISPATCH = "would_dispatch"
    WOULD_BLOCK = "would_block"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class SakuraCapabilitySnapshot:
    target_alias: str
    supported_capabilities: frozenset[SakuraCapability]
    observed_at: datetime
    max_age: timedelta
    cabin_temperature_range_c: tuple[int | float, int | float] | None = None

    def __post_init__(self) -> None:
        _require_safe_ref("target_alias", self.target_alias)
        if not isinstance(self.supported_capabilities, frozenset):
            raise TypeError("supported_capabilities must be a frozenset")
        if any(
            not isinstance(item, SakuraCapability)
            for item in self.supported_capabilities
        ):
            raise TypeError(
                "supported_capabilities must contain SakuraCapability values"
            )
        _require_aware("observed_at", self.observed_at)
        _require_duration("max_age", self.max_age)
        if self.cabin_temperature_range_c is not None:
            limits = self.cabin_temperature_range_c
            if not isinstance(limits, tuple) or len(limits) != 2:
                raise TypeError(
                    "cabin_temperature_range_c must be a two-item tuple or None"
                )
            minimum, maximum = limits
            _require_number("temperature minimum", minimum)
            _require_number("temperature maximum", maximum)
            if minimum > maximum:
                raise ValueError("temperature minimum must not exceed maximum")

    def is_fresh_at(self, value: datetime) -> bool:
        _require_aware("evaluated_at", value)
        age = value.astimezone(timezone.utc) - self.observed_at.astimezone(timezone.utc)
        return timedelta(0) <= age <= self.max_age


@dataclass(frozen=True)
class _Request:
    operation_id: str
    target_alias: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_safe_ref("operation_id", self.operation_id)
        _require_safe_ref("target_alias", self.target_alias)
        _require_aware("requested_at", self.requested_at)


@dataclass(frozen=True)
class SakuraStartChargingRequest(_Request):
    operation: SakuraOperation = SakuraOperation.START_CHARGING

    @property
    def capability(self) -> SakuraCapability:
        return SakuraCapability.CHARGE

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_fixed_operation(
            self.operation,
            SakuraOperation.START_CHARGING,
        )


@dataclass(frozen=True)
class SakuraClimateRequest(_Request):
    enabled: bool

    @property
    def operation(self) -> SakuraOperation:
        return (
            SakuraOperation.START_CLIMATE
            if self.enabled
            else SakuraOperation.STOP_CLIMATE
        )

    @property
    def capability(self) -> SakuraCapability:
        return SakuraCapability.CLIMATE

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a boolean")


@dataclass(frozen=True)
class SakuraSetCabinTemperatureRequest(_Request):
    temperature_c: int | float
    operation: SakuraOperation = SakuraOperation.SET_CABIN_TEMPERATURE

    @property
    def capability(self) -> SakuraCapability:
        return SakuraCapability.TEMPERATURE

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_number("temperature_c", self.temperature_c)
        _require_fixed_operation(
            self.operation,
            SakuraOperation.SET_CABIN_TEMPERATURE,
        )


@dataclass(frozen=True)
class SakuraLockRequest(_Request):
    operation: SakuraOperation = SakuraOperation.LOCK

    @property
    def capability(self) -> SakuraCapability:
        return SakuraCapability.LOCK

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_fixed_operation(self.operation, SakuraOperation.LOCK)


SakuraOperationRequest: TypeAlias = (
    SakuraStartChargingRequest
    | SakuraClimateRequest
    | SakuraSetCabinTemperatureRequest
    | SakuraLockRequest
)


@dataclass(frozen=True)
class SakuraDryRunResult:
    request: SakuraOperationRequest
    outcome: SakuraDryRunOutcome
    reason_code: str
    dispatch_attempted: bool = False

    def __post_init__(self) -> None:
        if self.dispatch_attempted:
            raise ValueError("Sakura dry-run cannot dispatch")


class SakuraDryRunPlanner:
    """Evaluate supported requests without a route to the vehicle."""

    def __init__(self, snapshot: SakuraCapabilitySnapshot) -> None:
        self._snapshot = snapshot

    def evaluate(
        self,
        request: SakuraOperationRequest,
        *,
        evaluated_at: datetime,
    ) -> SakuraDryRunResult:
        _require_aware("evaluated_at", evaluated_at)
        if not isinstance(
            request,
            (
                SakuraStartChargingRequest,
                SakuraClimateRequest,
                SakuraSetCabinTemperatureRequest,
                SakuraLockRequest,
            ),
        ):
            raise TypeError("request must be a typed Sakura operation request")
        if request.target_alias != self._snapshot.target_alias:
            return self._result(
                request, SakuraDryRunOutcome.WOULD_BLOCK, "target_mismatch"
            )
        if request.requested_at > evaluated_at:
            return self._result(
                request,
                SakuraDryRunOutcome.WOULD_BLOCK,
                "request_time_invalid",
            )
        if not self._snapshot.is_fresh_at(evaluated_at):
            return self._result(
                request,
                SakuraDryRunOutcome.INDETERMINATE,
                "capability_snapshot_stale",
            )
        if request.capability not in self._snapshot.supported_capabilities:
            return self._result(
                request,
                SakuraDryRunOutcome.WOULD_BLOCK,
                "capability_not_advertised",
            )
        if isinstance(request, SakuraSetCabinTemperatureRequest):
            limits = self._snapshot.cabin_temperature_range_c
            if limits is None:
                return self._result(
                    request,
                    SakuraDryRunOutcome.INDETERMINATE,
                    "parameter_capability_missing",
                )
            if not limits[0] <= request.temperature_c <= limits[1]:
                return self._result(
                    request,
                    SakuraDryRunOutcome.WOULD_BLOCK,
                    "parameter_not_advertised",
                )
        return self._result(
            request,
            SakuraDryRunOutcome.WOULD_DISPATCH,
            "conditions_satisfied",
        )

    @staticmethod
    def _result(
        request: SakuraOperationRequest,
        outcome: SakuraDryRunOutcome,
        reason_code: str,
    ) -> SakuraDryRunResult:
        return SakuraDryRunResult(request, outcome, reason_code)


SakuraDryRunOperationAdapter = SakuraDryRunPlanner


def is_supported_operation_name(value: str) -> bool:
    """Return false for unlock and unknown strings; never coerce or bypass."""

    if not isinstance(value, str) or value in UNSUPPORTED_OPERATION_NAMES:
        return False
    try:
        SakuraOperation(value)
    except ValueError:
        return False
    return True


def _require_fixed_operation(
    actual: SakuraOperation, expected: SakuraOperation
) -> None:
    if actual is not expected:
        raise ValueError(f"operation must be {expected.value}")


def _require_safe_ref(name: str, value: str) -> None:
    if not isinstance(value, str) or not _SAFE_REF.fullmatch(value):
        raise ValueError(f"{name} must be a safe opaque reference")


def _require_number(name: str, value: int | float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


def _require_aware(name: str, value: datetime) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _require_duration(name: str, value: timedelta) -> None:
    if not isinstance(value, timedelta):
        raise TypeError(f"{name} must be a timedelta")
    if value <= timedelta(0) or value > timedelta(hours=24):
        raise ValueError(f"{name} must be greater than 0 and at most 24 hours")
