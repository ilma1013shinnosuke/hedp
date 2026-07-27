"""Offline-only operation contract for Miele scheduled-program start.

This module intentionally contains no HTTP path, request payload, credentials,
or dispatch implementation.  It can only decide whether a typed request would
be eligible for a future, separately qualified transport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import re
from typing import Protocol

from hedp.observations import Quality
from hedp.operations.execution import ExecutionCapability


_SAFE_REF = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class MieleCommand(str, Enum):
    START_SCHEDULED_PROGRAM = "START_SCHEDULED_PROGRAM"


class MieleDryRunOutcome(str, Enum):
    WOULD_DISPATCH = "would_dispatch"
    WOULD_BLOCK = "would_block"
    INDETERMINATE = "indeterminate"


class MieleDispatchReceiptStatus(str, Enum):
    """Sanitized receipt state from a future, separately qualified writer.

    This does not describe an HTTP response.  A production transport may set
    ``ACCEPTED`` only after the vendor's actual acknowledgement semantics have
    been verified for the target device and API version.
    """

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class MieleStartVerificationOutcome(str, Enum):
    """Outcome of the read-back contract after a future dispatch attempt."""

    MATCHED = "matched"
    NOT_MATCHED = "not_matched"
    INDETERMINATE = "indeterminate"


class MieleReadbackUnavailable(RuntimeError):
    """Sanitized read-only failure; raw vendor details must not be included."""


@dataclass(frozen=True)
class StartScheduledProgramRequest:
    """Vendor-neutral request to start the program already scheduled on-device."""

    operation_id: str
    target_alias: str
    requested_at: datetime
    command: MieleCommand = field(
        default=MieleCommand.START_SCHEDULED_PROGRAM,
        init=False,
    )

    def __post_init__(self) -> None:
        _require_safe_ref("operation_id", self.operation_id)
        _require_safe_ref("target_alias", self.target_alias)
        _require_aware("requested_at", self.requested_at)


@dataclass(frozen=True)
class MieleCapabilitySnapshot:
    """Short-lived, externally observed operation capability.

    ``supported_commands`` records only what a qualified discovery path
    observed.  It is not derived from model names or documentation guesses.
    """

    target_alias: str
    supported_commands: frozenset[MieleCommand]
    observed_at: datetime
    max_age: timedelta
    maximum_readback_age: timedelta
    startable_status_codes: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        _require_safe_ref("target_alias", self.target_alias)
        if not isinstance(self.supported_commands, frozenset):
            raise TypeError("supported_commands must be a frozenset")
        if any(not isinstance(item, MieleCommand) for item in self.supported_commands):
            raise TypeError("supported_commands must contain MieleCommand values")
        _require_aware("observed_at", self.observed_at)
        _require_duration("max_age", self.max_age)
        _require_duration("maximum_readback_age", self.maximum_readback_age)
        if not isinstance(self.startable_status_codes, frozenset):
            raise TypeError("startable_status_codes must be a frozenset")
        for value in self.startable_status_codes:
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError("startable_status_codes must contain integers")

    def is_fresh_at(self, value: datetime) -> bool:
        _require_aware("evaluated_at", value)
        age = value.astimezone(timezone.utc) - self.observed_at.astimezone(timezone.utc)
        return timedelta(0) <= age <= self.max_age


@dataclass(frozen=True)
class MieleProgramReadback:
    """Sanitized state used only as pre-dispatch evidence."""

    target_alias: str
    observed_at: datetime
    quality: Quality
    status_code: int | None
    program_id: int | None

    def __post_init__(self) -> None:
        _require_safe_ref("target_alias", self.target_alias)
        _require_aware("observed_at", self.observed_at)
        if not isinstance(self.quality, Quality):
            raise TypeError("quality must be a Quality value")
        for name in ("status_code", "program_id"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int)
            ):
                raise TypeError(f"{name} must be an integer or None")
        if self.quality is Quality.GOOD and self.status_code is None:
            raise ValueError("good readback must include status_code")


class MieleProgramReadbackPort(Protocol):
    """Read-only port; implementations must not start or modify a program."""

    def read_program_state(self, target_alias: str) -> MieleProgramReadback: ...


@dataclass(frozen=True)
class MieleDispatchReceipt:
    """Minimal, vendor-neutral acknowledgement evidence.

    The offline adapter never creates a receipt for an actual device command.
    This type exists so a later writer cannot report a completed operation from
    a post-state observation alone.
    """

    target_alias: str
    status: MieleDispatchReceiptStatus
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_safe_ref("target_alias", self.target_alias)
        if not isinstance(self.status, MieleDispatchReceiptStatus):
            raise TypeError("status must be a MieleDispatchReceiptStatus")
        _require_aware("observed_at", self.observed_at)


@dataclass(frozen=True)
class MieleStartVerificationCapability:
    """Observed evidence needed to interpret a post-start read-back.

    ``started_status_codes`` has no default interpretation.  It must be
    populated only from a qualified, read-only observation for the exact API
    and appliance.  An empty set deliberately leaves verification unresolved.
    """

    target_alias: str
    observed_at: datetime
    max_age: timedelta
    maximum_readback_age: timedelta
    started_status_codes: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        _require_safe_ref("target_alias", self.target_alias)
        _require_aware("observed_at", self.observed_at)
        _require_duration("max_age", self.max_age)
        _require_duration("maximum_readback_age", self.maximum_readback_age)
        if not isinstance(self.started_status_codes, frozenset):
            raise TypeError("started_status_codes must be a frozenset")
        for value in self.started_status_codes:
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError("started_status_codes must contain integers")

    def is_fresh_at(self, value: datetime) -> bool:
        _require_aware("evaluated_at", value)
        age = value.astimezone(timezone.utc) - self.observed_at.astimezone(
            timezone.utc
        )
        return timedelta(0) <= age <= self.max_age


@dataclass(frozen=True)
class MieleStartVerificationResult:
    """Result contract for a future writer's acceptance and read-back check."""

    target_alias: str
    outcome: MieleStartVerificationOutcome
    reason_code: str
    receipt: MieleDispatchReceipt | None = None
    post_dispatch_readback: MieleProgramReadback | None = None

    def __post_init__(self) -> None:
        _require_safe_ref("target_alias", self.target_alias)
        if not isinstance(self.outcome, MieleStartVerificationOutcome):
            raise TypeError("outcome must be a MieleStartVerificationOutcome")
        _require_safe_ref("reason_code", self.reason_code)
        if self.receipt is not None and self.receipt.target_alias != self.target_alias:
            raise ValueError("receipt target must match verification target")
        if (
            self.post_dispatch_readback is not None
            and self.post_dispatch_readback.target_alias != self.target_alias
        ):
            raise ValueError("readback target must match verification target")


class MieleStartVerificationGate:
    """Evaluate receipt plus post-start read-back without dispatching anything."""

    def __init__(self, capability: MieleStartVerificationCapability) -> None:
        self._capability = capability

    def assess(
        self,
        *,
        receipt: MieleDispatchReceipt | None,
        post_dispatch_readback: MieleProgramReadback | None,
        evaluated_at: datetime,
    ) -> MieleStartVerificationResult:
        _require_aware("evaluated_at", evaluated_at)
        capability = self._capability
        target_alias = capability.target_alias
        if not capability.is_fresh_at(evaluated_at):
            return _verification(target_alias, "verification_capability_stale")
        if not capability.started_status_codes:
            return _verification(target_alias, "started_status_capability_missing")
        if receipt is None:
            return _verification(target_alias, "dispatch_receipt_unavailable")
        if receipt.target_alias != target_alias:
            return _verification(target_alias, "receipt_target_mismatch", receipt=receipt)
        if receipt.status is MieleDispatchReceiptStatus.UNKNOWN:
            return _verification(target_alias, "dispatch_receipt_unknown", receipt=receipt)
        if receipt.status is MieleDispatchReceiptStatus.REJECTED:
            return _verification(
                target_alias,
                "dispatch_rejected",
                outcome=MieleStartVerificationOutcome.NOT_MATCHED,
                receipt=receipt,
            )
        if post_dispatch_readback is None:
            return _verification(target_alias, "post_dispatch_readback_unavailable", receipt=receipt)
        if post_dispatch_readback.target_alias != target_alias:
            return _verification(
                target_alias,
                "post_dispatch_readback_target_mismatch",
                receipt=receipt,
                post_dispatch_readback=post_dispatch_readback,
            )
        if post_dispatch_readback.quality is not Quality.GOOD:
            return _verification(
                target_alias,
                "post_dispatch_readback_quality_insufficient",
                receipt=receipt,
                post_dispatch_readback=post_dispatch_readback,
            )
        age = evaluated_at.astimezone(timezone.utc) - post_dispatch_readback.observed_at.astimezone(
            timezone.utc
        )
        if not timedelta(0) <= age <= capability.maximum_readback_age:
            return _verification(
                target_alias,
                "post_dispatch_readback_not_fresh",
                receipt=receipt,
                post_dispatch_readback=post_dispatch_readback,
            )
        if post_dispatch_readback.status_code not in capability.started_status_codes:
            return _verification(
                target_alias,
                "post_start_status_not_matched",
                outcome=MieleStartVerificationOutcome.NOT_MATCHED,
                receipt=receipt,
                post_dispatch_readback=post_dispatch_readback,
            )
        return _verification(
            target_alias,
            "post_start_status_matched",
            outcome=MieleStartVerificationOutcome.MATCHED,
            receipt=receipt,
            post_dispatch_readback=post_dispatch_readback,
        )


@dataclass(frozen=True)
class MieleDryRunResult:
    request: StartScheduledProgramRequest
    outcome: MieleDryRunOutcome
    reason_code: str
    readback: MieleProgramReadback | None = None
    dispatch_attempted: bool = False

    def __post_init__(self) -> None:
        if self.dispatch_attempted:
            raise ValueError("Miele dry-run cannot dispatch")


class MieleOperationGate:
    """Capability and readback gate with no write transport."""

    def __init__(
        self,
        capability_snapshot: MieleCapabilitySnapshot,
        readback_port: MieleProgramReadbackPort,
    ) -> None:
        self._capability_snapshot = capability_snapshot
        self._readback_port = readback_port

    def assess(
        self,
        request: StartScheduledProgramRequest,
        *,
        evaluated_at: datetime,
    ) -> MieleDryRunResult:
        _require_aware("evaluated_at", evaluated_at)
        snapshot = self._capability_snapshot
        if request.target_alias != snapshot.target_alias:
            return _result(request, MieleDryRunOutcome.WOULD_BLOCK, "target_mismatch")
        if request.requested_at > evaluated_at:
            return _result(
                request,
                MieleDryRunOutcome.WOULD_BLOCK,
                "request_time_invalid",
            )
        if not snapshot.is_fresh_at(evaluated_at):
            return _result(
                request,
                MieleDryRunOutcome.INDETERMINATE,
                "capability_snapshot_stale",
            )
        if request.command not in snapshot.supported_commands:
            return _result(
                request,
                MieleDryRunOutcome.WOULD_BLOCK,
                "command_not_advertised",
            )

        try:
            readback = self._readback_port.read_program_state(request.target_alias)
        except MieleReadbackUnavailable:
            return _result(
                request,
                MieleDryRunOutcome.INDETERMINATE,
                "readback_unavailable",
            )
        if readback.target_alias != request.target_alias:
            return _result(
                request,
                MieleDryRunOutcome.INDETERMINATE,
                "readback_target_mismatch",
                readback,
            )
        if readback.quality is not Quality.GOOD:
            return _result(
                request,
                MieleDryRunOutcome.INDETERMINATE,
                "readback_quality_insufficient",
                readback,
            )
        if readback.program_id is None:
            return _result(
                request,
                MieleDryRunOutcome.INDETERMINATE,
                "scheduled_program_missing",
                readback,
            )
        if not snapshot.startable_status_codes:
            return _result(
                request,
                MieleDryRunOutcome.INDETERMINATE,
                "startable_status_capability_missing",
                readback,
            )
        if readback.status_code not in snapshot.startable_status_codes:
            return _result(
                request,
                MieleDryRunOutcome.WOULD_BLOCK,
                "status_not_startable",
                readback,
            )
        age = evaluated_at.astimezone(timezone.utc) - readback.observed_at.astimezone(
            timezone.utc
        )
        if not timedelta(0) <= age <= snapshot.maximum_readback_age:
            return _result(
                request,
                MieleDryRunOutcome.INDETERMINATE,
                "readback_not_fresh",
                readback,
            )
        return _result(
            request,
            MieleDryRunOutcome.WOULD_DISPATCH,
            "conditions_satisfied",
            readback,
        )


def scheduled_program_execution_capability(
    capability_snapshot: MieleCapabilitySnapshot,
) -> ExecutionCapability:
    """Expose the Miele operation to the common ExecutionGate in Shadow Mode.

    This is a capability declaration only: it registers no dispatch port and
    cannot send a vendor request.  The Miele-specific gate must still assess
    the observed capability and read-back before any later writer is eligible.
    """

    if MieleCommand.START_SCHEDULED_PROGRAM not in capability_snapshot.supported_commands:
        raise ValueError("start command must be observed before capability registration")
    return ExecutionCapability(
        target_alias=capability_snapshot.target_alias,
        capability="miele-start-scheduled-program",
        control_owner="miele",
        allowed_desired_states=(MieleCommand.START_SCHEDULED_PROGRAM,),
        maximum_state_age=capability_snapshot.maximum_readback_age,
    )


def _result(
    request: StartScheduledProgramRequest,
    outcome: MieleDryRunOutcome,
    reason_code: str,
    readback: MieleProgramReadback | None = None,
) -> MieleDryRunResult:
    return MieleDryRunResult(request, outcome, reason_code, readback)


def _verification(
    target_alias: str,
    reason_code: str,
    *,
    outcome: MieleStartVerificationOutcome = MieleStartVerificationOutcome.INDETERMINATE,
    receipt: MieleDispatchReceipt | None = None,
    post_dispatch_readback: MieleProgramReadback | None = None,
) -> MieleStartVerificationResult:
    return MieleStartVerificationResult(
        target_alias=target_alias,
        outcome=outcome,
        reason_code=reason_code,
        receipt=receipt,
        post_dispatch_readback=post_dispatch_readback,
    )


def _require_safe_ref(name: str, value: str) -> None:
    if not isinstance(value, str) or not _SAFE_REF.fullmatch(value):
        raise ValueError(f"{name} must be a safe opaque reference")


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
