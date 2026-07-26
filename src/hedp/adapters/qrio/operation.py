"""Operation-only Qrio adapter with single-dispatch trigger semantics."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol

from hedp.observations import Quality

from .models import LockPosition, LockStatus


_SAFE_REF = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class QrioCommand(str, Enum):
    LOCK = "lock"
    UNLOCK = "unlock"


class DispatchStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    TRANSPORT_ERROR = "transport_error"
    UNKNOWN = "unknown"


class VerificationStatus(str, Enum):
    MATCHED = "matched"
    NOT_MATCHED = "not_matched"
    UNAVAILABLE = "unavailable"


class OperationOutcome(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class QrioJobStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PENDING = "pending"
    UNAVAILABLE = "unavailable"


class QrioOperationError(RuntimeError):
    """Privacy-safe vendor operation failure."""


class QrioOperationTimeout(QrioOperationError):
    """The transport timed out and dispatch completion is unknown."""


class QrioOperationTransportError(QrioOperationError):
    """A known, privacy-safe operation transport failure."""


class QrioJobCheckError(QrioOperationError):
    """A known, privacy-safe job-status failure."""


class QrioReadbackError(QrioOperationError):
    """A known, privacy-safe read-back failure."""


@dataclass(frozen=True)
class QrioOperationRequest:
    """A pre-gated request supplied by the common Execution layer."""

    operation_id: str
    target_alias: str
    command: QrioCommand
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_safe_ref("operation_id", self.operation_id)
        _require_safe_ref("target_alias", self.target_alias)
        _require_aware("requested_at", self.requested_at)


@dataclass(frozen=True)
class QrioVendorReceipt:
    """Sanitized response; raw vendor payloads are never retained here."""

    status: DispatchStatus
    vendor_reference: str | None = field(default=None, repr=False)
    summary_code: str | None = None

    def __post_init__(self) -> None:
        for name in ("vendor_reference", "summary_code"):
            value = getattr(self, name)
            if value is not None:
                _require_safe_ref(name, value)


@dataclass(frozen=True)
class QrioDispatchReceipt:
    operation_id: str
    target_alias: str
    command: QrioCommand
    attempted_at: datetime
    attempt_number: int
    status: DispatchStatus
    summary_code: str | None


@dataclass(frozen=True)
class QrioVerificationResult:
    status: VerificationStatus
    expected_position: LockPosition
    observed_position: LockPosition | None
    observed_at: str | None
    method: str = "status_readback"


@dataclass(frozen=True)
class QrioOperationResult:
    receipt: QrioDispatchReceipt
    verification: QrioVerificationResult
    outcome: OperationOutcome


class QrioOperationTransport(Protocol):
    """Vendor write port. One call must cause at most one dispatch."""

    def dispatch(
        self,
        *,
        target_alias: str,
        command: QrioCommand,
        operation_id: str,
    ) -> QrioVendorReceipt: ...


class QrioStatusReader(Protocol):
    """Existing read path reused only for post-dispatch reconciliation."""

    def status(self) -> LockStatus: ...


class QrioJobChecker(Protocol):
    """Read-only operation-job check supplied by a vendor integration."""

    def check(self, vendor_reference: str) -> QrioJobStatus: ...


class QrioOperationAdapter:
    """Perform exactly one dispatch and, when accepted, one status read-back.

    Lock and unlock are trigger operations. This adapter never retries a
    dispatch after a timeout, exception, ambiguous response, or failed
    verification.
    """

    def __init__(
        self,
        transport: QrioOperationTransport,
        status_reader: QrioStatusReader,
        *,
        job_checker: QrioJobChecker | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    ) -> None:
        self._transport = transport
        self._status_reader = status_reader
        self._job_checker = job_checker
        self._clock = clock

    def execute(self, request: QrioOperationRequest) -> QrioOperationResult:
        attempted_at = self._clock()
        _require_aware("attempted_at", attempted_at)
        try:
            vendor = self._transport.dispatch(
                target_alias=request.target_alias,
                command=request.command,
                operation_id=request.operation_id,
            )
        except QrioOperationTimeout:
            vendor = QrioVendorReceipt(
                DispatchStatus.TIMEOUT,
                summary_code="dispatch-timeout",
            )
        except QrioOperationTransportError:
            vendor = QrioVendorReceipt(
                DispatchStatus.TRANSPORT_ERROR,
                summary_code="transport-error",
            )

        receipt = QrioDispatchReceipt(
            operation_id=request.operation_id,
            target_alias=request.target_alias,
            command=request.command,
            attempted_at=attempted_at,
            attempt_number=1,
            status=vendor.status,
            summary_code=vendor.summary_code,
        )
        expected = (
            LockPosition.LOCKED
            if request.command is QrioCommand.LOCK
            else LockPosition.UNLOCKED
        )

        if vendor.status is not DispatchStatus.ACCEPTED:
            verification = _unavailable_verification(expected)
            outcome = (
                OperationOutcome.FAILED
                if vendor.status is DispatchStatus.REJECTED
                else OperationOutcome.UNKNOWN
            )
            return QrioOperationResult(receipt, verification, outcome)

        if vendor.vendor_reference is not None:
            if self._job_checker is None:
                return QrioOperationResult(
                    receipt,
                    _unavailable_verification(expected),
                    OperationOutcome.UNKNOWN,
                )
            try:
                job_status = self._job_checker.check(vendor.vendor_reference)
            except QrioJobCheckError:
                return QrioOperationResult(
                    receipt,
                    _unavailable_verification(expected),
                    OperationOutcome.UNKNOWN,
                )
            if job_status is QrioJobStatus.FAILED:
                return QrioOperationResult(
                    receipt,
                    _unavailable_verification(expected),
                    OperationOutcome.FAILED,
                )
            if job_status is not QrioJobStatus.SUCCEEDED:
                return QrioOperationResult(
                    receipt,
                    _unavailable_verification(expected),
                    OperationOutcome.UNKNOWN,
                )

        try:
            observed = self._status_reader.status()
        except QrioReadbackError:
            return QrioOperationResult(
                receipt,
                _unavailable_verification(expected),
                OperationOutcome.UNKNOWN,
            )

        position = observed.position.value
        if observed.position.quality is not Quality.GOOD or position is None:
            return QrioOperationResult(
                receipt,
                _unavailable_verification(expected),
                OperationOutcome.UNKNOWN,
            )
        matched = position is expected
        verification = QrioVerificationResult(
            status=(
                VerificationStatus.MATCHED
                if matched
                else VerificationStatus.NOT_MATCHED
            ),
            expected_position=expected,
            observed_position=position,
            observed_at=observed.time.observed_at,
        )
        return QrioOperationResult(
            receipt,
            verification,
            OperationOutcome.COMPLETED if matched else OperationOutcome.FAILED,
        )


def _unavailable_verification(
    expected: LockPosition,
) -> QrioVerificationResult:
    return QrioVerificationResult(
        status=VerificationStatus.UNAVAILABLE,
        expected_position=expected,
        observed_position=None,
        observed_at=None,
    )


def _require_safe_ref(name: str, value: str) -> None:
    if not _SAFE_REF.fullmatch(value):
        raise ValueError(f"{name} must be a safe opaque reference")


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
