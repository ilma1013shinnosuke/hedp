"""Operation-only ECHONET Lite adapter for runtime-confirmed EcoCute Set EPCs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import re
import secrets
import time
from typing import Callable, Protocol

from .echonet import EchonetProperty, FrameError
from .transport import (
    EcoCuteReadOnlyUdpTransport,
    EcoCuteSetExchange,
    EchonetResponseError,
    EchonetTransportError,
)


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
    NOT_SUPPORTED = "not_supported"


class OperationOutcome(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RuntimeCapabilitySnapshot:
    """Short-lived property maps observed from this exact safe target alias."""

    target_alias: str
    set_epcs: frozenset[int]
    get_epcs: frozenset[int]
    observed_at: datetime
    max_age: timedelta

    def __post_init__(self) -> None:
        _validate_target_alias(self.target_alias)
        if not self.set_epcs:
            raise ValueError("set_epcs must not be empty")
        if any(
            isinstance(epc, bool) or not isinstance(epc, int) or not 0 <= epc <= 255
            for epc in self.set_epcs | self.get_epcs
        ):
            raise ValueError("observed EPCs must be byte values")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.max_age <= timedelta(0) or self.max_age > timedelta(hours=24):
            raise ValueError("max_age must be greater than 0 and at most 24 hours")

    def is_fresh_at(self, value: datetime) -> bool:
        age = value.astimezone(timezone.utc) - self.observed_at.astimezone(timezone.utc)
        return timedelta(0) <= age <= self.max_age


@dataclass(frozen=True)
class EcoCuteSetCommand:
    """One exact Set value proven outside this adapter.

    ``target_alias`` is a safe household alias.  It must not contain an IP,
    serial number, MAC address, or other vendor identifier.
    """

    target_alias: str
    epc: int
    data: bytes
    expected_readback: bytes | None

    def __post_init__(self) -> None:
        _validate_target_alias(self.target_alias)
        if isinstance(self.epc, bool) or not isinstance(self.epc, int):
            raise TypeError("epc must be an integer")
        if not 0 <= self.epc <= 0xFF:
            raise ValueError("epc must be between 0 and 255")
        if not isinstance(self.data, bytes) or not self.data:
            raise ValueError("data must be non-empty bytes")
        if len(self.data) > 0xFF:
            raise ValueError("data must contain at most 255 bytes")
        if self.expected_readback is not None and not isinstance(
            self.expected_readback, bytes
        ):
            raise TypeError("expected_readback must be bytes or None")


@dataclass(frozen=True)
class EcoCuteDispatchReceipt:
    attempted_at: str
    target_alias: str
    epc: int
    status: DispatchStatus
    attempt_number: int = 1
    transport: str = "echonet_lite_unicast_udp"


@dataclass(frozen=True)
class EcoCuteVerificationResult:
    checked_at: str
    target_alias: str
    epc: int
    status: VerificationStatus
    method: str
    quality: str


@dataclass(frozen=True)
class EcoCuteOperationResult:
    dispatch: EcoCuteDispatchReceipt
    verification: EcoCuteVerificationResult
    outcome: OperationOutcome


class SetTransport(Protocol):
    def set(
        self, *, transaction_id: int, epc: int, data: bytes, instance_code: int
    ) -> EcoCuteSetExchange: ...


class ReadTransport(Protocol):
    def get(
        self, *, transaction_id: int, epcs: tuple[int, ...], instance_code: int
    ) -> object: ...


class EcoCuteOperationAdapter:
    """Dispatch one Set once, then verify through the separately injected reader.

    There is deliberately no retry loop.  A timeout or unknown result must
    return to ExecutionGate instead of blindly repeating a heating trigger.
    """

    def __init__(
        self,
        set_transport: SetTransport,
        read_transport: EcoCuteReadOnlyUdpTransport | ReadTransport,
        *,
        capability_snapshot: RuntimeCapabilitySnapshot,
        instance_code: int = 1,
        readback_delay_seconds: float = 1.0,
        sleeper: Callable[[float], None] = time.sleep,
        transaction_id_factory: Callable[[], int] = (
            lambda: secrets.randbelow(0x10000)
        ),
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if not 1 <= instance_code <= 0xFF:
            raise ValueError("instance_code must be between 1 and 255")
        if not 0 <= readback_delay_seconds <= 30:
            raise ValueError("readback_delay_seconds must be between 0 and 30")
        self._set_transport = set_transport
        self._read_transport = read_transport
        self._capability_snapshot = capability_snapshot
        self._instance_code = instance_code
        self._readback_delay_seconds = readback_delay_seconds
        self._sleeper = sleeper
        self._transaction_id_factory = transaction_id_factory
        self._now = now

    def execute(self, command: EcoCuteSetCommand) -> EcoCuteOperationResult:
        gate_time = self._aware_now()
        if command.target_alias != self._capability_snapshot.target_alias:
            raise PermissionError("capability snapshot belongs to a different target")
        if not self._capability_snapshot.is_fresh_at(gate_time):
            raise PermissionError("runtime capability snapshot is stale")
        if command.epc not in self._capability_snapshot.set_epcs:
            raise PermissionError("EPC was not advertised in the runtime Set map")

        attempted_at = self._format_time(gate_time)
        try:
            self._set_transport.set(
                transaction_id=self._transaction_id(),
                epc=command.epc,
                data=command.data,
                instance_code=self._instance_code,
            )
        except EchonetResponseError:
            return self._result(
                command, attempted_at, DispatchStatus.REJECTED,
                VerificationStatus.NOT_SUPPORTED,
            )
        except TimeoutError:
            return self._result(
                command, attempted_at, DispatchStatus.TIMEOUT,
                VerificationStatus.UNAVAILABLE,
            )
        except EchonetTransportError:
            return self._result(
                command, attempted_at, DispatchStatus.TRANSPORT_ERROR,
                VerificationStatus.UNAVAILABLE,
            )
        except OSError:
            return self._result(
                command, attempted_at, DispatchStatus.TRANSPORT_ERROR,
                VerificationStatus.UNAVAILABLE,
            )

        dispatch = EcoCuteDispatchReceipt(
            attempted_at, command.target_alias, command.epc, DispatchStatus.ACCEPTED
        )
        if self._readback_delay_seconds:
            self._sleeper(self._readback_delay_seconds)
        verification = self._verify(command)
        return EcoCuteOperationResult(
            dispatch, verification, _outcome(dispatch.status, verification.status)
        )

    def _verify(self, command: EcoCuteSetCommand) -> EcoCuteVerificationResult:
        checked_at = self._timestamp()
        if (
            command.expected_readback is None
            or command.epc not in self._capability_snapshot.get_epcs
        ):
            return EcoCuteVerificationResult(
                checked_at,
                command.target_alias,
                command.epc,
                VerificationStatus.NOT_SUPPORTED,
                "echonet_lite_get",
                "unknown",
            )
        try:
            exchange = self._read_transport.get(
                transaction_id=self._transaction_id(),
                epcs=(command.epc,),
                instance_code=self._instance_code,
            )
            frame = getattr(exchange, "frame")
            prop = _single_property(frame.properties, command.epc)
        except (AttributeError, FrameError, EchonetResponseError, EchonetTransportError):
            return EcoCuteVerificationResult(
                checked_at,
                command.target_alias,
                command.epc,
                VerificationStatus.UNAVAILABLE,
                "echonet_lite_get",
                "missing",
            )
        status = (
            VerificationStatus.MATCHED
            if prop.data == command.expected_readback
            else VerificationStatus.NOT_MATCHED
        )
        return EcoCuteVerificationResult(
            checked_at,
            command.target_alias,
            command.epc,
            status,
            "echonet_lite_get",
            "good",
        )

    def _result(
        self,
        command: EcoCuteSetCommand,
        attempted_at: str,
        dispatch_status: DispatchStatus,
        verification_status: VerificationStatus,
    ) -> EcoCuteOperationResult:
        dispatch = EcoCuteDispatchReceipt(
                attempted_at,
                command.target_alias,
                command.epc,
                dispatch_status,
            )
        verification = EcoCuteVerificationResult(
                self._timestamp(),
                command.target_alias,
                command.epc,
                verification_status,
                "echonet_lite_get",
                "missing" if verification_status is VerificationStatus.UNAVAILABLE else "unknown",
            )
        return EcoCuteOperationResult(
            dispatch,
            verification,
            _outcome(dispatch.status, verification.status),
        )

    def _transaction_id(self) -> int:
        value = self._transaction_id_factory()
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("transaction ID factory must return an integer")
        if not 0 <= value <= 0xFFFF:
            raise ValueError("transaction ID factory returned an invalid value")
        return value

    def _timestamp(self) -> str:
        return self._format_time(self._aware_now())

    def _aware_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("now must return a timezone-aware datetime")
        return value

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()


def _single_property(
    properties: tuple[EchonetProperty, ...], epc: int
) -> EchonetProperty:
    matched = tuple(item for item in properties if item.epc == epc)
    if len(matched) != 1:
        raise FrameError("verification response does not contain exactly one EPC")
    return matched[0]


def _validate_target_alias(value: str) -> None:
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,79}", value) is None:
        raise ValueError("target_alias must be a safe non-address alias")


def _outcome(
    dispatch: DispatchStatus, verification: VerificationStatus
) -> OperationOutcome:
    if dispatch is DispatchStatus.ACCEPTED and verification is VerificationStatus.MATCHED:
        return OperationOutcome.COMPLETED
    if dispatch is DispatchStatus.REJECTED or verification is VerificationStatus.NOT_MATCHED:
        return OperationOutcome.FAILED
    return OperationOutcome.UNKNOWN
