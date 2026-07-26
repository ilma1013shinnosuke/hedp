"""Offline-safe SwitchBot robot operation contracts.

The module contains no HTTP POST method.  Vendor command names are limited to
the official model-specific vocabulary represented below.  This adapter is not
a production execution entry point: non-dry-run dispatch is permitted only for
an explicitly marked fixture transport.  A future live transport must be
reachable only through the common Execution coordinator.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Protocol

from hedp.observations import Quality
from hedp.operations.execution import ExecutionCapability

from .robot_state import RobotState, RobotWorkingStatus
from .secondary_state import (
    LightPower,
    RgbColor,
    SecondaryDeviceKind,
    SecondaryDeviceObservation,
    SecondaryField,
)


_SAFE_REF = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class RobotCommand(str, Enum):
    START = "start"
    STOP = "stop"
    DOCK = "dock"
    PAUSE = "pause"
    START_CLEAN = "start_clean"


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


class SwitchBotOperationError(RuntimeError):
    pass


class SwitchBotOperationTimeout(SwitchBotOperationError):
    pass


class SwitchBotTransportError(SwitchBotOperationError):
    pass


@dataclass(frozen=True)
class S10CleanParameters:
    action: str
    fan_level: int
    water_level: int
    times: int = 1

    def __post_init__(self) -> None:
        if self.action not in {"sweep", "sweep_mop"}:
            raise ValueError("action must be sweep or sweep_mop")
        if (
            isinstance(self.fan_level, bool)
            or not isinstance(self.fan_level, int)
            or not 1 <= self.fan_level <= 4
        ):
            raise ValueError("fan_level must be between 1 and 4")
        if (
            isinstance(self.water_level, bool)
            or not isinstance(self.water_level, int)
            or not 1 <= self.water_level <= 2
        ):
            raise ValueError("water_level must be between 1 and 2")
        if (
            isinstance(self.times, bool)
            or not isinstance(self.times, int)
            or self.times != 1
        ):
            raise ValueError("times must be 1 until another value is evidence-backed")


@dataclass(frozen=True)
class RobotVendorCommand:
    command: str
    parameter: str | dict[str, object]
    command_type: str = "command"

    def __post_init__(self) -> None:
        if self.command not in {"start", "stop", "dock", "pause", "startClean"}:
            raise ValueError("command is not in the official-confirmed vocabulary")
        if self.command_type != "command":
            raise ValueError("robot command_type must be command")

    def payload(self) -> dict[str, object]:
        return {
            "command": self.command,
            "parameter": self.parameter,
            "commandType": self.command_type,
        }


_LEGACY_DEVICE_TYPES = frozenset(
    {
        "robot vacuum cleaner s1",
        "robot vacuum cleaner s1 plus",
        "k10+",
        "mini robot vacuum k10+",
    }
)
_S10_DEVICE_TYPES = frozenset(
    {
        "floor cleaning robot s10",
        "robot vacuum cleaner s10",
    }
)
_OFFICIAL_COMMANDS = {
    **{
        device_type: frozenset(
            {RobotCommand.START, RobotCommand.STOP, RobotCommand.DOCK}
        )
        for device_type in _LEGACY_DEVICE_TYPES
    },
    **{
        device_type: frozenset(
            {RobotCommand.START_CLEAN, RobotCommand.PAUSE, RobotCommand.DOCK}
        )
        for device_type in _S10_DEVICE_TYPES
    },
}


def official_commands_for(device_type: str) -> frozenset[RobotCommand]:
    if not isinstance(device_type, str):
        raise TypeError("device_type must be a string")
    return _OFFICIAL_COMMANDS.get(device_type.strip().casefold(), frozenset())


@dataclass(frozen=True)
class RuntimeCapabilitySnapshot:
    target_alias: str
    device_type: str
    commands: frozenset[RobotCommand]
    observed_at: datetime
    max_age: timedelta

    def __post_init__(self) -> None:
        _require_safe_ref("target_alias", self.target_alias)
        if not isinstance(self.commands, frozenset) or any(
            not isinstance(command, RobotCommand) for command in self.commands
        ):
            raise TypeError("commands must be a frozenset of RobotCommand")
        official = official_commands_for(self.device_type)
        if not self.commands:
            raise ValueError("commands must not be empty")
        if not self.commands <= official:
            raise ValueError(
                "commands must be official-confirmed for this exact device type"
            )
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.max_age <= timedelta(0) or self.max_age > timedelta(hours=24):
            raise ValueError("max_age must be greater than 0 and at most 24 hours")

    def is_fresh_at(self, value: datetime) -> bool:
        age = value.astimezone(timezone.utc) - self.observed_at.astimezone(timezone.utc)
        return timedelta(0) <= age <= self.max_age


@dataclass(frozen=True)
class RobotOperationRequest:
    operation_id: str
    target_alias: str
    command: RobotCommand
    requested_at: datetime
    dry_run: bool = True
    clean_parameters: S10CleanParameters | None = None

    def __post_init__(self) -> None:
        _require_safe_ref("operation_id", self.operation_id)
        _require_safe_ref("target_alias", self.target_alias)
        if not isinstance(self.command, RobotCommand):
            raise TypeError("command must be RobotCommand")
        if not isinstance(self.dry_run, bool):
            raise TypeError("dry_run must be a boolean")
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("requested_at must be timezone-aware")
        if self.command is RobotCommand.START_CLEAN and self.clean_parameters is None:
            raise ValueError("start_clean requires S10CleanParameters")
        if (
            self.command is not RobotCommand.START_CLEAN
            and self.clean_parameters is not None
        ):
            raise ValueError("clean_parameters are only valid for start_clean")


@dataclass(frozen=True)
class RobotVendorReceipt:
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
class RobotDispatchReceipt:
    operation_id: str
    target_alias: str
    command: RobotCommand
    attempted_at: datetime
    attempt_number: int
    status: DispatchStatus
    summary_code: str | None


@dataclass(frozen=True)
class RobotVerificationResult:
    status: VerificationStatus
    expected: tuple[RobotWorkingStatus, ...]
    observed: RobotWorkingStatus | None
    observed_at: datetime | None
    method: str = "status_readback"


@dataclass(frozen=True)
class RobotOperationResult:
    dispatch: RobotDispatchReceipt
    verification: RobotVerificationResult
    outcome: OperationOutcome
    vendor_command: RobotVendorCommand


class RobotCommandTransport(Protocol):
    """Fixture-only dispatcher; one call causes at most one dispatch."""

    is_fixture: bool

    def dispatch(
        self, *, target_alias: str, command: RobotVendorCommand
    ) -> RobotVendorReceipt: ...


class RobotStateReader(Protocol):
    def read_state(self, target_alias: str) -> RobotState: ...


class RobotOperationAdapter:
    """Plan operations or exercise an explicitly marked offline fixture.

    Direct adapter execution is deliberately unavailable for production.  The
    common Execution coordinator remains the only permitted future live entry
    point.
    """

    def __init__(
        self,
        capability_snapshot: RuntimeCapabilitySnapshot,
        *,
        transport: RobotCommandTransport | None = None,
        state_reader: RobotStateReader | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if transport is not None and getattr(transport, "is_fixture", None) is not True:
            raise ValueError(
                "SwitchBot transport must be explicitly marked fixture-only"
            )
        self._capability_snapshot = capability_snapshot
        self._transport = transport
        self._state_reader = state_reader
        self._clock = clock

    def execute(self, request: RobotOperationRequest) -> RobotOperationResult:
        attempted_at = self._aware_now()
        self._gate(request, attempted_at)
        vendor_command = _vendor_command(request)
        expected = _expected_statuses(request.command)
        if request.dry_run:
            return RobotOperationResult(
                RobotDispatchReceipt(
                    request.operation_id,
                    request.target_alias,
                    request.command,
                    attempted_at,
                    0,
                    DispatchStatus.DRY_RUN,
                    None,
                ),
                RobotVerificationResult(
                    VerificationStatus.NOT_ATTEMPTED,
                    expected,
                    None,
                    None,
                    "dry_run",
                ),
                OperationOutcome.PLANNED,
                vendor_command,
            )
        if self._transport is None:
            raise PermissionError(
                "SwitchBot operations are dry-run or fixture-only"
            )
        try:
            vendor = self._transport.dispatch(
                target_alias=request.target_alias,
                command=vendor_command,
            )
        except SwitchBotOperationTimeout:
            vendor = RobotVendorReceipt(DispatchStatus.TIMEOUT, "dispatch-timeout")
        except SwitchBotTransportError:
            vendor = RobotVendorReceipt(
                DispatchStatus.TRANSPORT_ERROR, "transport-error"
            )
        receipt = RobotDispatchReceipt(
            request.operation_id,
            request.target_alias,
            request.command,
            attempted_at,
            1,
            vendor.status,
            vendor.summary_code,
        )
        if vendor.status is not DispatchStatus.ACCEPTED:
            return RobotOperationResult(
                receipt,
                RobotVerificationResult(
                    VerificationStatus.UNAVAILABLE, expected, None, None
                ),
                (
                    OperationOutcome.FAILED
                    if vendor.status is DispatchStatus.REJECTED
                    else OperationOutcome.UNKNOWN
                ),
                vendor_command,
            )
        if self._state_reader is None:
            return RobotOperationResult(
                receipt,
                RobotVerificationResult(
                    VerificationStatus.UNAVAILABLE, expected, None, None
                ),
                OperationOutcome.UNKNOWN,
                vendor_command,
            )
        try:
            state = self._state_reader.read_state(request.target_alias)
        except SwitchBotTransportError:
            return RobotOperationResult(
                receipt,
                RobotVerificationResult(
                    VerificationStatus.UNAVAILABLE, expected, None, None
                ),
                OperationOutcome.UNKNOWN,
                vendor_command,
            )
        verified_at = self._aware_now()
        readback_is_fresh = (
            attempted_at.astimezone(timezone.utc)
            <= state.observed_at.astimezone(timezone.utc)
            <= verified_at.astimezone(timezone.utc)
        )
        if state.quality is not Quality.GOOD or not readback_is_fresh:
            return RobotOperationResult(
                receipt,
                RobotVerificationResult(
                    VerificationStatus.UNAVAILABLE,
                    expected,
                    state.working_status,
                    state.observed_at,
                    "fresh_good_status_readback",
                ),
                OperationOutcome.UNKNOWN,
                vendor_command,
            )
        matched = state.working_status in expected
        return RobotOperationResult(
            receipt,
            RobotVerificationResult(
                (
                    VerificationStatus.MATCHED
                    if matched
                    else VerificationStatus.NOT_MATCHED
                ),
                expected,
                state.working_status,
                state.observed_at,
            ),
            OperationOutcome.COMPLETED if matched else OperationOutcome.FAILED,
            vendor_command,
        )

    def _gate(self, request: RobotOperationRequest, checked_at: datetime) -> None:
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


LIGHT_EXECUTION_CAPABILITY = "switchbot-light-state-set"


class LightCommand(str, Enum):
    SET_POWER = "set_power"
    SET_BRIGHTNESS = "set_brightness"
    SET_COLOR = "set_color"


@dataclass(frozen=True)
class LightDesiredState:
    command: LightCommand
    value: LightPower | int | RgbColor

    def __post_init__(self) -> None:
        if not isinstance(self.command, LightCommand):
            raise TypeError("command must be LightCommand")
        if self.command is LightCommand.SET_POWER:
            if not isinstance(self.value, LightPower):
                raise TypeError("set_power value must be LightPower")
        elif self.command is LightCommand.SET_BRIGHTNESS:
            if (
                isinstance(self.value, bool)
                or not isinstance(self.value, int)
                or not 0 <= self.value <= 100
            ):
                raise ValueError("set_brightness value must be from 0 to 100")
        elif not isinstance(self.value, RgbColor):
            raise TypeError("set_color value must be RgbColor")

    def canonical_value(self) -> str | int:
        if isinstance(self.value, Enum):
            return self.value.value
        if isinstance(self.value, RgbColor):
            return self.value.canonical()
        return self.value


@dataclass(frozen=True)
class LightCapabilitySnapshot:
    target_alias: str
    kind: SecondaryDeviceKind
    commands: frozenset[LightCommand]
    observed_at: datetime
    max_age: timedelta

    def __post_init__(self) -> None:
        _require_safe_ref("target_alias", self.target_alias)
        if self.kind not in {
            SecondaryDeviceKind.E26_SMART_BULB,
            SecondaryDeviceKind.STRIP_LIGHT_3,
        }:
            raise ValueError("light capability requires a registered light kind")
        if not isinstance(self.commands, frozenset) or any(
            not isinstance(command, LightCommand) for command in self.commands
        ):
            raise TypeError("commands must be a frozenset of LightCommand")
        if not self.commands:
            raise ValueError("commands must not be empty")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.max_age <= timedelta(0) or self.max_age > timedelta(hours=24):
            raise ValueError("max_age must be greater than 0 and at most 24 hours")

    def is_fresh_at(self, value: datetime) -> bool:
        age = value.astimezone(timezone.utc) - self.observed_at.astimezone(timezone.utc)
        return timedelta(0) <= age <= self.max_age

    def execution_capability(self, *, control_owner: str) -> ExecutionCapability:
        """Build the common gate descriptor; this does not install a dispatch port."""

        return ExecutionCapability(
            target_alias=self.target_alias,
            capability=LIGHT_EXECUTION_CAPABILITY,
            control_owner=control_owner,
            allowed_desired_states=(),
            desired_state_validator=lambda value: (
                isinstance(value, LightDesiredState)
                and value.command in self.commands
            ),
            maximum_state_age=self.max_age,
            approval_required=True,
        )


@dataclass(frozen=True)
class LightOperationRequest:
    operation_id: str
    target_alias: str
    desired_state: LightDesiredState
    requested_at: datetime
    dry_run: bool = True

    def __post_init__(self) -> None:
        _require_safe_ref("operation_id", self.operation_id)
        _require_safe_ref("target_alias", self.target_alias)
        if not isinstance(self.desired_state, LightDesiredState):
            raise TypeError("desired_state must be LightDesiredState")
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("requested_at must be timezone-aware")
        if not isinstance(self.dry_run, bool):
            raise TypeError("dry_run must be a boolean")


@dataclass(frozen=True)
class LightVendorReceipt:
    status: DispatchStatus
    summary_code: str | None = None

    def __post_init__(self) -> None:
        if self.status is DispatchStatus.DRY_RUN:
            raise ValueError("a fixture receipt cannot report dry_run")
        if self.summary_code is not None:
            _require_safe_ref("summary_code", self.summary_code)


@dataclass(frozen=True)
class LightDispatchReceipt:
    operation_id: str
    target_alias: str
    attempted_at: datetime
    attempt_number: int
    status: DispatchStatus


@dataclass(frozen=True)
class LightVerificationResult:
    status: VerificationStatus
    field: SecondaryField
    expected: str | int
    observed: str | int | None
    observed_at: datetime | None
    method: str = "typed_secondary_state_readback"


@dataclass(frozen=True)
class LightOperationResult:
    dispatch: LightDispatchReceipt
    verification: LightVerificationResult
    outcome: OperationOutcome


class LightFixtureTransport(Protocol):
    """Semantic fixture only; no vendor endpoint or payload is admitted."""

    is_fixture: bool

    def dispatch(self, request: LightOperationRequest) -> LightVendorReceipt: ...


class LightStateReader(Protocol):
    def read_state(self, target_alias: str) -> SecondaryDeviceObservation: ...


class LightOperationAdapter:
    """Dry-run and fixture read-back contract for registered lights.

    This class contains no vendor payload and is not a production execution
    entry point.  A future live port must be installed behind the common
    Execution coordinator.
    """

    def __init__(
        self,
        capability_snapshot: LightCapabilitySnapshot,
        *,
        transport: LightFixtureTransport | None = None,
        state_reader: LightStateReader | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if transport is not None and getattr(transport, "is_fixture", None) is not True:
            raise ValueError("light transport must be explicitly marked fixture-only")
        self._capability_snapshot = capability_snapshot
        self._transport = transport
        self._state_reader = state_reader
        self._clock = clock

    def execute(self, request: LightOperationRequest) -> LightOperationResult:
        attempted_at = self._aware_now()
        self._gate(request, attempted_at)
        field_name = _light_field(request.desired_state.command)
        expected = request.desired_state.canonical_value()
        if request.dry_run:
            return LightOperationResult(
                LightDispatchReceipt(
                    request.operation_id,
                    request.target_alias,
                    attempted_at,
                    0,
                    DispatchStatus.DRY_RUN,
                ),
                LightVerificationResult(
                    VerificationStatus.NOT_ATTEMPTED,
                    field_name,
                    expected,
                    None,
                    None,
                    "dry_run",
                ),
                OperationOutcome.PLANNED,
            )
        if self._transport is None:
            raise PermissionError("light operations are dry-run or fixture-only")
        try:
            vendor = self._transport.dispatch(request)
        except SwitchBotOperationTimeout:
            vendor = LightVendorReceipt(DispatchStatus.TIMEOUT, "dispatch-timeout")
        except SwitchBotTransportError:
            vendor = LightVendorReceipt(
                DispatchStatus.TRANSPORT_ERROR,
                "transport-error",
            )
        receipt = LightDispatchReceipt(
            request.operation_id,
            request.target_alias,
            attempted_at,
            1,
            vendor.status,
        )
        if vendor.status is not DispatchStatus.ACCEPTED:
            return LightOperationResult(
                receipt,
                LightVerificationResult(
                    VerificationStatus.UNAVAILABLE,
                    field_name,
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
            return LightOperationResult(
                receipt,
                LightVerificationResult(
                    VerificationStatus.UNAVAILABLE,
                    field_name,
                    expected,
                    None,
                    None,
                ),
                OperationOutcome.UNKNOWN,
            )
        try:
            state = self._state_reader.read_state(request.target_alias)
        except SwitchBotTransportError:
            return LightOperationResult(
                receipt,
                LightVerificationResult(
                    VerificationStatus.UNAVAILABLE,
                    field_name,
                    expected,
                    None,
                    None,
                ),
                OperationOutcome.UNKNOWN,
            )
        verified_at = self._aware_now()
        observed_field = state.field(field_name)
        observed_value = (
            _canonical_secondary_value(observed_field.observation.value)
            if observed_field is not None
            else None
        )
        fresh = (
            attempted_at.astimezone(timezone.utc)
            <= state.observed_at.astimezone(timezone.utc)
            <= verified_at.astimezone(timezone.utc)
        )
        if (
            state.target_alias != request.target_alias
            or state.kind is not self._capability_snapshot.kind
            or observed_field is None
            or observed_field.observation.quality is not Quality.GOOD
            or not fresh
        ):
            return LightOperationResult(
                receipt,
                LightVerificationResult(
                    VerificationStatus.UNAVAILABLE,
                    field_name,
                    expected,
                    observed_value,
                    state.observed_at,
                    "fresh_good_typed_secondary_state_readback",
                ),
                OperationOutcome.UNKNOWN,
            )
        matched = observed_value == expected
        return LightOperationResult(
            receipt,
            LightVerificationResult(
                (
                    VerificationStatus.MATCHED
                    if matched
                    else VerificationStatus.NOT_MATCHED
                ),
                field_name,
                expected,
                observed_value,
                state.observed_at,
            ),
            OperationOutcome.COMPLETED if matched else OperationOutcome.FAILED,
        )

    def _gate(self, request: LightOperationRequest, evaluated_at: datetime) -> None:
        if request.target_alias != self._capability_snapshot.target_alias:
            raise PermissionError("capability snapshot belongs to another target")
        if request.requested_at > evaluated_at:
            raise PermissionError("request time is in the future")
        if not self._capability_snapshot.is_fresh_at(evaluated_at):
            raise PermissionError("light capability snapshot is stale")
        if request.desired_state.command not in self._capability_snapshot.commands:
            raise PermissionError("light command is absent from the capability snapshot")

    def _aware_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value


def _vendor_command(request: RobotOperationRequest) -> RobotVendorCommand:
    names = {
        RobotCommand.START: "start",
        RobotCommand.STOP: "stop",
        RobotCommand.DOCK: "dock",
        RobotCommand.PAUSE: "pause",
        RobotCommand.START_CLEAN: "startClean",
    }
    if request.clean_parameters is None:
        parameter: str | dict[str, object] = "default"
    else:
        parameter = {
            "action": request.clean_parameters.action,
            "param": {
                "fanLevel": request.clean_parameters.fan_level,
                "waterLevel": request.clean_parameters.water_level,
                "times": request.clean_parameters.times,
            },
        }
    return RobotVendorCommand(names[request.command], parameter)


def _expected_statuses(
    command: RobotCommand,
) -> tuple[RobotWorkingStatus, ...]:
    if command in {RobotCommand.START, RobotCommand.START_CLEAN}:
        return (RobotWorkingStatus.CLEANING,)
    if command is RobotCommand.STOP:
        return (RobotWorkingStatus.STANDBY,)
    if command is RobotCommand.PAUSE:
        return (RobotWorkingStatus.PAUSED,)
    return (
        RobotWorkingStatus.RETURNING_TO_DOCK,
        RobotWorkingStatus.CHARGING,
        RobotWorkingStatus.CHARGE_DONE,
    )


def _require_safe_ref(name: str, value: str) -> None:
    if not isinstance(value, str) or not _SAFE_REF.fullmatch(value):
        raise ValueError(f"{name} must be a safe opaque reference")


def _light_field(command: LightCommand) -> SecondaryField:
    return {
        LightCommand.SET_POWER: SecondaryField.POWER,
        LightCommand.SET_BRIGHTNESS: SecondaryField.BRIGHTNESS,
        LightCommand.SET_COLOR: SecondaryField.COLOR,
    }[command]


def _canonical_secondary_value(value: object) -> str | int | None:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, RgbColor):
        return value.canonical()
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None
