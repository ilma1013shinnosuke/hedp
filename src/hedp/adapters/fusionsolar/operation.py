"""Offline-only FusionSolar operation evidence contracts.

No HTTP route or live transport is defined here.  The unconfirmed stop,
charge, and discharge shapes may be assessed as dry-runs or exercised against
an explicitly marked fixture transport only.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Protocol

from hedp.observations import Quality

from .state import BatteryMode, FusionSolarControlState, GenerationStatus


_SAFE_REF = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class FusionSolarCommand(str, Enum):
    STOP_GENERATION = "stop_generation"
    CHARGE = "charge"
    DISCHARGE = "discharge"


class DispatchStatus(str, Enum):
    DRY_RUN = "dry_run"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    TRANSPORT_ERROR = "transport_error"
    UNKNOWN = "unknown"


class VerificationStatus(str, Enum):
    NOT_ATTEMPTED = "not_attempted"
    MATCHED = "matched"
    NOT_MATCHED = "not_matched"
    UNAVAILABLE = "unavailable"


class OperationOutcome(str, Enum):
    PLANNED = "planned"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class FusionSolarOperationError(RuntimeError):
    """Privacy-safe base error for an injected operation transport."""


class FusionSolarOperationTimeout(FusionSolarOperationError):
    pass


class FusionSolarTransportError(FusionSolarOperationError):
    pass


@dataclass(frozen=True)
class RuntimeCapabilitySnapshot:
    target_alias: str
    commands: frozenset[FusionSolarCommand]
    observed_at: datetime
    max_age: timedelta

    def __post_init__(self) -> None:
        _require_safe_ref("target_alias", self.target_alias)
        if not isinstance(self.commands, frozenset) or any(
            not isinstance(command, FusionSolarCommand) for command in self.commands
        ):
            raise TypeError("commands must be a frozenset of FusionSolarCommand")
        if not self.commands:
            raise ValueError("commands must not be empty")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.max_age <= timedelta(0) or self.max_age > timedelta(hours=24):
            raise ValueError("max_age must be greater than 0 and at most 24 hours")

    def is_fresh_at(self, value: datetime) -> bool:
        age = value.astimezone(timezone.utc) - self.observed_at.astimezone(timezone.utc)
        return timedelta(0) <= age <= self.max_age


@dataclass(frozen=True)
class FusionSolarOperationRequest:
    operation_id: str
    target_alias: str
    command: FusionSolarCommand
    requested_at: datetime
    dry_run: bool = True

    def __post_init__(self) -> None:
        _require_safe_ref("operation_id", self.operation_id)
        _require_safe_ref("target_alias", self.target_alias)
        if not isinstance(self.command, FusionSolarCommand):
            raise TypeError("command must be FusionSolarCommand")
        if not isinstance(self.dry_run, bool):
            raise TypeError("dry_run must be a boolean")
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("requested_at must be timezone-aware")


@dataclass(frozen=True)
class FusionSolarVendorReceipt:
    status: DispatchStatus
    summary_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, DispatchStatus):
            raise TypeError("status must be DispatchStatus")
        if self.status is DispatchStatus.DRY_RUN:
            raise ValueError("a vendor receipt cannot report dry_run")
        if self.summary_code is not None:
            _require_safe_ref("summary_code", self.summary_code)


@dataclass(frozen=True)
class FusionSolarDispatchReceipt:
    operation_id: str
    target_alias: str
    command: FusionSolarCommand
    attempted_at: datetime
    attempt_number: int
    status: DispatchStatus
    summary_code: str | None


@dataclass(frozen=True)
class FusionSolarVerificationResult:
    status: VerificationStatus
    expected: str
    observed: str | None
    observed_at: datetime | None
    method: str = "qualified_state_readback"


@dataclass(frozen=True)
class FusionSolarOperationResult:
    dispatch: FusionSolarDispatchReceipt
    verification: FusionSolarVerificationResult
    outcome: OperationOutcome


class FusionSolarOperationTransport(Protocol):
    """Fixture-only dispatcher used to preserve offline operation evidence."""

    is_fixture: bool

    def dispatch(
        self, request: FusionSolarOperationRequest
    ) -> FusionSolarVendorReceipt: ...


class FusionSolarStateReader(Protocol):
    """Separately qualified read-only state source."""

    def read_state(self, target_alias: str) -> FusionSolarControlState: ...


class FusionSolarOperationAdapter:
    """Gate one dry-run or one fixture dispatch followed by safe read-back."""

    def __init__(
        self,
        capability_snapshot: RuntimeCapabilitySnapshot,
        *,
        transport: FusionSolarOperationTransport | None = None,
        state_reader: FusionSolarStateReader | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if transport is not None and getattr(transport, "is_fixture", None) is not True:
            raise ValueError(
                "FusionSolar transport must be explicitly marked fixture-only"
            )
        self._capability_snapshot = capability_snapshot
        self._transport = transport
        self._state_reader = state_reader
        self._clock = clock

    def execute(
        self, request: FusionSolarOperationRequest
    ) -> FusionSolarOperationResult:
        attempted_at = self._aware_now()
        self._gate(request, attempted_at)
        expected = _expected_value(request.command)
        if request.dry_run:
            return FusionSolarOperationResult(
                FusionSolarDispatchReceipt(
                    request.operation_id,
                    request.target_alias,
                    request.command,
                    attempted_at,
                    0,
                    DispatchStatus.DRY_RUN,
                    None,
                ),
                FusionSolarVerificationResult(
                    VerificationStatus.NOT_ATTEMPTED,
                    expected,
                    None,
                    None,
                    "dry_run",
                ),
                OperationOutcome.PLANNED,
            )
        if self._transport is None:
            raise PermissionError("FusionSolar operations are dry-run or fixture-only")

        try:
            vendor = self._transport.dispatch(request)
        except FusionSolarOperationTimeout:
            vendor = FusionSolarVendorReceipt(
                DispatchStatus.TIMEOUT, "dispatch-timeout"
            )
        except FusionSolarTransportError:
            vendor = FusionSolarVendorReceipt(
                DispatchStatus.TRANSPORT_ERROR, "transport-error"
            )
        receipt = FusionSolarDispatchReceipt(
            request.operation_id,
            request.target_alias,
            request.command,
            attempted_at,
            1,
            vendor.status,
            vendor.summary_code,
        )
        if vendor.status is not DispatchStatus.ACCEPTED:
            return FusionSolarOperationResult(
                receipt,
                FusionSolarVerificationResult(
                    VerificationStatus.UNAVAILABLE,
                    expected,
                    None,
                    None,
                ),
                (
                    OperationOutcome.FAILED
                    if vendor.status is DispatchStatus.REJECTED
                    else OperationOutcome.UNKNOWN
                ),
            )
        if self._state_reader is None:
            return FusionSolarOperationResult(
                receipt,
                FusionSolarVerificationResult(
                    VerificationStatus.UNAVAILABLE,
                    expected,
                    None,
                    None,
                ),
                OperationOutcome.UNKNOWN,
            )

        try:
            state = self._state_reader.read_state(request.target_alias)
        except FusionSolarTransportError:
            return FusionSolarOperationResult(
                receipt,
                FusionSolarVerificationResult(
                    VerificationStatus.UNAVAILABLE,
                    expected,
                    None,
                    None,
                ),
                OperationOutcome.UNKNOWN,
            )
        observed = _observed_value(request.command, state)
        quality = _observed_quality(request.command, state)
        verified_at = self._aware_now()
        readback_is_fresh = (
            attempted_at.astimezone(timezone.utc)
            <= state.observed_at.astimezone(timezone.utc)
            <= verified_at.astimezone(timezone.utc)
        )
        if quality is not Quality.GOOD or not readback_is_fresh:
            return FusionSolarOperationResult(
                receipt,
                FusionSolarVerificationResult(
                    VerificationStatus.UNAVAILABLE,
                    expected,
                    observed,
                    state.observed_at,
                    "qualified_fresh_good_state_readback",
                ),
                OperationOutcome.UNKNOWN,
            )
        matched = observed == expected
        return FusionSolarOperationResult(
            receipt,
            FusionSolarVerificationResult(
                (
                    VerificationStatus.MATCHED
                    if matched
                    else VerificationStatus.NOT_MATCHED
                ),
                expected,
                observed,
                state.observed_at,
            ),
            OperationOutcome.COMPLETED if matched else OperationOutcome.FAILED,
        )

    def _gate(self, request: FusionSolarOperationRequest, checked_at: datetime) -> None:
        if request.target_alias != self._capability_snapshot.target_alias:
            raise PermissionError("capability snapshot belongs to another target")
        if not self._capability_snapshot.is_fresh_at(checked_at):
            raise PermissionError("runtime capability snapshot is stale")
        if request.command not in self._capability_snapshot.commands:
            raise PermissionError("command is absent from the capability snapshot")

    def _aware_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value


def _expected_value(command: FusionSolarCommand) -> str:
    return {
        FusionSolarCommand.STOP_GENERATION: GenerationStatus.STOPPED.value,
        FusionSolarCommand.CHARGE: BatteryMode.CHARGING.value,
        FusionSolarCommand.DISCHARGE: BatteryMode.DISCHARGING.value,
    }[command]


def _observed_value(command: FusionSolarCommand, state: FusionSolarControlState) -> str:
    if command is FusionSolarCommand.STOP_GENERATION:
        return state.generation_status.value
    return state.battery_mode.value


def _observed_quality(
    command: FusionSolarCommand, state: FusionSolarControlState
) -> Quality:
    if command is FusionSolarCommand.STOP_GENERATION:
        return state.generation_quality
    return state.battery_quality


def _require_safe_ref(name: str, value: str) -> None:
    if not isinstance(value, str) or not _SAFE_REF.fullmatch(value):
        raise ValueError(f"{name} must be a safe opaque reference")
