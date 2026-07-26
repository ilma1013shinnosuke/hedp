"""Vendor-neutral ExecutionGate and single-dispatch coordinator.

This module has no database, scheduler, network, or device dependency.  A
vendor adapter is reachable only through an explicitly injected dispatch port.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from threading import Lock
from typing import Any, Protocol

from .shadow_execution import EvidenceQuality, Intent, StateEvidence


class ExecutionMode(str, Enum):
    SHADOW = "shadow"
    FIXTURE = "fixture"


class GateStatus(str, Enum):
    PASS = "pass"
    BLOCKED = "blocked"
    EXPIRED = "expired"
    UNAVAILABLE = "unavailable"


class ExecutionOutcome(str, Enum):
    WOULD_DISPATCH = "would_dispatch"
    BLOCKED = "blocked"
    EXPIRED = "expired"
    UNAVAILABLE = "unavailable"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ExecutionCapability:
    target_alias: str
    capability: str
    control_owner: str
    allowed_desired_states: tuple[Any, ...]
    maximum_state_age: timedelta
    accepted_qualities: tuple[EvidenceQuality, ...] = (EvidenceQuality.GOOD,)
    approval_required: bool = True

    def __post_init__(self) -> None:
        if not self.allowed_desired_states:
            raise ValueError("allowed_desired_states must not be empty")
        if self.maximum_state_age <= timedelta(0):
            raise ValueError("maximum_state_age must be positive")
        if not self.accepted_qualities:
            raise ValueError("accepted_qualities must not be empty")


@dataclass(frozen=True)
class Authorization:
    """Short-lived permission created outside the adapter."""

    operation_id: str
    requester: str
    target_alias: str
    capability: str
    desired_state: Any
    granted_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_aware("granted_at", self.granted_at)
        _require_aware("expires_at", self.expires_at)
        if self.expires_at <= self.granted_at:
            raise ValueError("authorization expiry must follow grant time")


@dataclass(frozen=True)
class AdapterExecutionResult:
    """Sanitized adapter result. Vendor identifiers and raw payloads are absent."""

    dispatch_status: str
    verification_status: str
    outcome: ExecutionOutcome


class ExecutionPort(Protocol):
    def execute(self, intent: Intent) -> AdapterExecutionResult: ...


@dataclass(frozen=True)
class GateDecision:
    status: GateStatus
    reason_code: str


@dataclass(frozen=True)
class ExecutionAuditEvent:
    phase: str
    operation_id: str
    correlation_id: str
    target_alias: str
    capability: str
    reason_code: str | None = None
    dispatch_attempted: bool = False

    def __post_init__(self) -> None:
        if self.phase not in {
            "received",
            "gate_checking",
            "ready",
            "dispatching",
            "verifying",
            "finished",
        }:
            raise ValueError("invalid execution phase")

    def to_dict(self) -> dict[str, str | bool | None]:
        return {
            "phase": self.phase,
            "operation_id": self.operation_id,
            "correlation_id": self.correlation_id,
            "target_alias": self.target_alias,
            "capability": self.capability,
            "reason_code": self.reason_code,
            "dispatch_attempted": self.dispatch_attempted,
        }


@dataclass(frozen=True)
class ExecutionResult:
    gate: GateDecision
    outcome: ExecutionOutcome
    adapter_result: AdapterExecutionResult | None
    audit_events: tuple[ExecutionAuditEvent, ...]
    dispatch_attempted: bool


@dataclass
class OperationRegistry:
    """Atomic process-local replay protection.

    Durable replay protection is deliberately deferred until its DB design and
    restart semantics are approved.  A claimed operation ID is never released
    automatically, including when the adapter returns an unknown result.
    """

    _operation_ids: set[str] = field(default_factory=set)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def claim(self, operation_id: str) -> bool:
        with self._lock:
            if operation_id in self._operation_ids:
                return False
            self._operation_ids.add(operation_id)
            return True


class ExecutionCoordinator:
    """Validate once and call an injected adapter at most once."""

    def __init__(
        self,
        capabilities: tuple[ExecutionCapability, ...],
        ports: dict[tuple[str, str], ExecutionPort] | None = None,
        *,
        registry: OperationRegistry | None = None,
    ) -> None:
        self._capabilities = {
            (item.target_alias, item.capability): item for item in capabilities
        }
        if len(self._capabilities) != len(capabilities):
            raise ValueError("target/capability pairs must be unique")
        self._ports = dict(ports or {})
        self._registry = registry or OperationRegistry()

    def execute(
        self,
        intent: Intent,
        *,
        evidence: StateEvidence | None,
        authorization: Authorization | None,
        evaluated_at: datetime,
        mode: ExecutionMode = ExecutionMode.SHADOW,
        manual_override_cooldown: timedelta = timedelta(0),
    ) -> ExecutionResult:
        _require_aware("evaluated_at", evaluated_at)
        if manual_override_cooldown < timedelta(0):
            raise ValueError("manual_override_cooldown must not be negative")

        events = [
            _event("received", intent),
            _event("gate_checking", intent),
        ]
        if mode is not ExecutionMode.SHADOW and mode is not ExecutionMode.FIXTURE:
            return _stopped(
                intent,
                GateDecision(GateStatus.BLOCKED, "execution_mode_invalid"),
                events,
            )
        gate = self._assess(
            intent,
            evidence=evidence,
            authorization=authorization,
            evaluated_at=evaluated_at,
            manual_override_cooldown=manual_override_cooldown,
        )
        if gate.status is not GateStatus.PASS:
            return _stopped(intent, gate, events)

        events.append(_event("ready", intent))
        if mode is ExecutionMode.SHADOW:
            events.append(_event("finished", intent, reason_code="shadow_only"))
            return ExecutionResult(
                gate,
                ExecutionOutcome.WOULD_DISPATCH,
                None,
                tuple(events),
                False,
            )

        port = self._ports.get((intent.target_alias, intent.capability))
        if port is None:
            return _stopped(
                intent,
                GateDecision(GateStatus.UNAVAILABLE, "dispatch_port_unavailable"),
                events,
            )
        if not self._registry.claim(intent.operation_id):
            return _stopped(
                intent,
                GateDecision(GateStatus.BLOCKED, "duplicate_operation_id"),
                events,
            )

        events.append(_event("dispatching", intent, dispatch_attempted=True))
        try:
            adapter_result = port.execute(intent)
        except Exception:
            # The operation may have reached the device.  Never retry here.
            events.append(
                _event(
                    "finished",
                    intent,
                    reason_code="adapter_result_unknown",
                    dispatch_attempted=True,
                )
            )
            return ExecutionResult(
                gate,
                ExecutionOutcome.UNKNOWN,
                None,
                tuple(events),
                True,
            )

        events.append(_event("verifying", intent, dispatch_attempted=True))
        events.append(
            _event(
                "finished",
                intent,
                reason_code=f"outcome_{adapter_result.outcome.value}",
                dispatch_attempted=True,
            )
        )
        return ExecutionResult(
            gate,
            adapter_result.outcome,
            adapter_result,
            tuple(events),
            True,
        )

    def _assess(
        self,
        intent: Intent,
        *,
        evidence: StateEvidence | None,
        authorization: Authorization | None,
        evaluated_at: datetime,
        manual_override_cooldown: timedelta,
    ) -> GateDecision:
        capability = self._capabilities.get(
            (intent.target_alias, intent.capability)
        )
        if capability is None:
            return GateDecision(GateStatus.BLOCKED, "capability_not_registered")
        if capability.control_owner != intent.control_owner:
            return GateDecision(GateStatus.BLOCKED, "owner_mismatch")
        if not any(
            type(intent.desired_state) is type(allowed)
            and intent.desired_state == allowed
            for allowed in capability.allowed_desired_states
        ):
            return GateDecision(GateStatus.BLOCKED, "desired_state_invalid")
        if intent.requested_at > evaluated_at:
            return GateDecision(GateStatus.BLOCKED, "request_time_invalid")
        if evaluated_at >= intent.expires_at:
            return GateDecision(GateStatus.EXPIRED, "intent_expired")
        if capability.approval_required:
            if authorization is None:
                return GateDecision(GateStatus.BLOCKED, "authorization_missing")
            if (
                authorization.operation_id != intent.operation_id
                or authorization.requester != intent.requester
                or authorization.target_alias != intent.target_alias
                or authorization.capability != intent.capability
                or type(authorization.desired_state) is not type(intent.desired_state)
                or authorization.desired_state != intent.desired_state
            ):
                return GateDecision(GateStatus.BLOCKED, "authorization_scope_mismatch")
            if authorization.granted_at > evaluated_at:
                return GateDecision(GateStatus.BLOCKED, "authorization_time_invalid")
            if evaluated_at >= authorization.expires_at:
                return GateDecision(GateStatus.EXPIRED, "authorization_expired")
        if evidence is None:
            return GateDecision(GateStatus.UNAVAILABLE, "state_missing")
        if evidence.quality not in capability.accepted_qualities:
            return GateDecision(GateStatus.UNAVAILABLE, "state_quality_insufficient")
        if evidence.observed_at > evaluated_at:
            return GateDecision(GateStatus.UNAVAILABLE, "state_time_invalid")
        if evaluated_at - evidence.observed_at > capability.maximum_state_age:
            return GateDecision(GateStatus.UNAVAILABLE, "state_not_fresh")
        if (
            evidence.manual_override_at is not None
            and evaluated_at - evidence.manual_override_at < manual_override_cooldown
        ):
            return GateDecision(GateStatus.BLOCKED, "manual_override_active")
        return GateDecision(GateStatus.PASS, "conditions_satisfied")


def function_port(
    function: Callable[[Intent], AdapterExecutionResult],
) -> ExecutionPort:
    """Make a small fixture or vendor bridge satisfy the execution port."""

    class _FunctionPort:
        def execute(self, intent: Intent) -> AdapterExecutionResult:
            return function(intent)

    return _FunctionPort()


def _stopped(
    intent: Intent,
    gate: GateDecision,
    events: list[ExecutionAuditEvent],
) -> ExecutionResult:
    outcome = {
        GateStatus.BLOCKED: ExecutionOutcome.BLOCKED,
        GateStatus.EXPIRED: ExecutionOutcome.EXPIRED,
        GateStatus.UNAVAILABLE: ExecutionOutcome.UNAVAILABLE,
    }[gate.status]
    events.append(_event("finished", intent, reason_code=gate.reason_code))
    return ExecutionResult(gate, outcome, None, tuple(events), False)


def _event(
    phase: str,
    intent: Intent,
    *,
    reason_code: str | None = None,
    dispatch_attempted: bool = False,
) -> ExecutionAuditEvent:
    return ExecutionAuditEvent(
        phase=phase,
        operation_id=intent.operation_id,
        correlation_id=intent.correlation_id,
        target_alias=intent.target_alias,
        capability=intent.capability,
        reason_code=reason_code,
        dispatch_attempted=dispatch_attempted,
    )


def _require_aware(name: str, value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
