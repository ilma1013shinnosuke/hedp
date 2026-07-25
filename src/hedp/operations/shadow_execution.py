"""Pure, offline-only evaluation of the Execution contract in Shadow Mode."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any


_SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
SCHEMA_VERSION = "1"


class GateStatus(str, Enum):
    PASS = "pass"
    BLOCKED = "blocked"
    EXPIRED = "expired"
    UNAVAILABLE = "unavailable"


class ShadowResult(str, Enum):
    WOULD_DISPATCH = "would_dispatch"
    WOULD_BLOCK = "would_block"
    INDETERMINATE = "indeterminate"


class EvidenceQuality(str, Enum):
    GOOD = "good"
    STALE = "stale"
    MISSING = "missing"
    INVALID = "invalid"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CapabilityDescriptor:
    """A pre-registered, vendor-neutral operation capability."""

    target_alias: str
    capability: str
    control_owner: str
    allowed_desired_states: tuple[Any, ...]
    verification_method: str
    maximum_state_age: timedelta
    accepted_qualities: tuple[EvidenceQuality, ...] = (EvidenceQuality.GOOD,)
    shadow_only: bool = True

    def __post_init__(self) -> None:
        _require_safe_name("target_alias", self.target_alias)
        _require_safe_name("capability", self.capability)
        _require_safe_name("control_owner", self.control_owner)
        _require_safe_name("verification_method", self.verification_method)
        if not self.shadow_only:
            raise ValueError("Shadow capability must remain shadow_only")
        if not self.allowed_desired_states:
            raise ValueError("allowed_desired_states must not be empty")
        if self.maximum_state_age <= timedelta(0):
            raise ValueError("maximum_state_age must be positive")
        if not self.accepted_qualities:
            raise ValueError("accepted_qualities must not be empty")


@dataclass(frozen=True)
class Intent:
    """Immutable request produced outside Layer 4."""

    operation_id: str
    requested_at: datetime
    expires_at: datetime
    requester: str
    reason: str
    target_alias: str
    capability: str
    desired_state: Any
    priority: int
    control_owner: str
    correlation_id: str

    def __post_init__(self) -> None:
        for name in (
            "operation_id",
            "requester",
            "target_alias",
            "capability",
            "control_owner",
            "correlation_id",
        ):
            _require_safe_name(name, getattr(self, name))
        _require_aware("requested_at", self.requested_at)
        _require_aware("expires_at", self.expires_at)
        if self.expires_at <= self.requested_at:
            raise ValueError("expires_at must be later than requested_at")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypeError("priority must be an integer")
        if not self.reason.strip():
            raise ValueError("reason must not be empty")


@dataclass(frozen=True)
class StateEvidence:
    """Already-normalized state injected by a fixture or future reader."""

    observed_at: datetime
    quality: EvidenceQuality
    current_state: Any
    manual_override_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_aware("observed_at", self.observed_at)
        if self.manual_override_at is not None:
            _require_aware("manual_override_at", self.manual_override_at)


@dataclass(frozen=True)
class GateResult:
    status: GateStatus
    reason_code: str
    state_observed_at: datetime | None
    state_quality: EvidenceQuality | None


@dataclass(frozen=True)
class AuditEvent:
    phase: str
    operation_id: str
    correlation_id: str
    target_alias: str
    control_owner: str
    verification_method: str | None
    gate_status: GateStatus | None = None
    reason_code: str | None = None
    shadow_result: ShadowResult | None = None
    dispatch_attempted: bool = False

    def __post_init__(self) -> None:
        if self.phase not in {"received", "gate_checking", "finished"}:
            raise ValueError("invalid Shadow audit phase")
        if self.dispatch_attempted:
            raise ValueError("Shadow Mode cannot dispatch")

    def to_dict(self) -> dict[str, str | bool | None]:
        return {
            "schema_version": SCHEMA_VERSION,
            "phase": self.phase,
            "operation_id": self.operation_id,
            "correlation_id": self.correlation_id,
            "target_alias": self.target_alias,
            "control_owner": self.control_owner,
            "verification_method": self.verification_method,
            "gate_status": self.gate_status.value if self.gate_status else None,
            "reason_code": self.reason_code,
            "shadow_result": self.shadow_result.value if self.shadow_result else None,
            "dispatch_attempted": False,
        }


@dataclass(frozen=True)
class ShadowAssessment:
    gate: GateResult
    result: ShadowResult
    audit_events: tuple[AuditEvent, ...]
    dispatch_attempted: bool = False

    def __post_init__(self) -> None:
        if self.dispatch_attempted:
            raise ValueError("Shadow Mode cannot dispatch")


@dataclass
class ShadowOperationRegistry:
    """Process-local replay protection; deliberately not durable."""

    operation_ids: set[str] = field(default_factory=set)

    def contains(self, operation_id: str) -> bool:
        return operation_id in self.operation_ids

    def record(self, operation_id: str) -> None:
        self.operation_ids.add(operation_id)


class ShadowExecutionGate:
    """Evaluate an Intent without importing or calling any Adapter."""

    def __init__(
        self,
        capabilities: tuple[CapabilityDescriptor, ...],
        *,
        registry: ShadowOperationRegistry | None = None,
    ) -> None:
        self._capabilities = {item.capability: item for item in capabilities}
        if len(self._capabilities) != len(capabilities):
            raise ValueError("capability names must be unique")
        self._registry = registry or ShadowOperationRegistry()

    def assess(
        self,
        intent: Intent,
        *,
        evidence: StateEvidence | None,
        evaluated_at: datetime,
        manual_override_cooldown: timedelta = timedelta(0),
    ) -> ShadowAssessment:
        _require_aware("evaluated_at", evaluated_at)
        if manual_override_cooldown < timedelta(0):
            raise ValueError("manual_override_cooldown must not be negative")

        capability = self._capabilities.get(intent.capability)
        verification = capability.verification_method if capability else None
        events = [
            self._event("received", intent, verification),
            self._event("gate_checking", intent, verification),
        ]

        if capability is None:
            return self._finish(
                intent, verification, events, GateStatus.BLOCKED, "unknown_capability"
            )
        if capability.target_alias != intent.target_alias:
            return self._finish(
                intent, verification, events, GateStatus.BLOCKED, "target_mismatch"
            )
        if capability.control_owner != intent.control_owner:
            return self._finish(
                intent, verification, events, GateStatus.BLOCKED, "owner_mismatch"
            )
        if not any(
            type(intent.desired_state) is type(allowed)
            and intent.desired_state == allowed
            for allowed in capability.allowed_desired_states
        ):
            return self._finish(
                intent,
                verification,
                events,
                GateStatus.BLOCKED,
                "desired_state_invalid",
            )
        if intent.requested_at > evaluated_at:
            return self._finish(
                intent,
                verification,
                events,
                GateStatus.BLOCKED,
                "request_time_invalid",
            )
        if evaluated_at >= intent.expires_at:
            return self._finish(
                intent, verification, events, GateStatus.EXPIRED, "intent_expired"
            )
        if evidence is None:
            return self._finish(
                intent, verification, events, GateStatus.UNAVAILABLE, "state_missing"
            )
        if evidence.quality not in capability.accepted_qualities:
            return self._finish(
                intent,
                verification,
                events,
                GateStatus.UNAVAILABLE,
                "state_quality_insufficient",
                evidence,
            )
        if evidence.observed_at > evaluated_at:
            return self._finish(
                intent,
                verification,
                events,
                GateStatus.UNAVAILABLE,
                "state_time_invalid",
                evidence,
            )
        if evaluated_at - evidence.observed_at > capability.maximum_state_age:
            return self._finish(
                intent,
                verification,
                events,
                GateStatus.UNAVAILABLE,
                "state_not_fresh",
                evidence,
            )
        if (
            evidence.manual_override_at is not None
            and evaluated_at - evidence.manual_override_at < manual_override_cooldown
        ):
            return self._finish(
                intent,
                verification,
                events,
                GateStatus.BLOCKED,
                "manual_override_active",
                evidence,
            )
        if self._registry.contains(intent.operation_id):
            return self._finish(
                intent,
                verification,
                events,
                GateStatus.BLOCKED,
                "duplicate_operation_id",
                evidence,
                record=False,
            )
        return self._finish(
            intent, verification, events, GateStatus.PASS, "conditions_satisfied", evidence
        )

    @staticmethod
    def _event(
        phase: str,
        intent: Intent,
        verification_method: str | None,
        *,
        gate_status: GateStatus | None = None,
        reason_code: str | None = None,
        shadow_result: ShadowResult | None = None,
    ) -> AuditEvent:
        return AuditEvent(
            phase=phase,
            operation_id=intent.operation_id,
            correlation_id=intent.correlation_id,
            target_alias=intent.target_alias,
            control_owner=intent.control_owner,
            verification_method=verification_method,
            gate_status=gate_status,
            reason_code=reason_code,
            shadow_result=shadow_result,
        )

    def _finish(
        self,
        intent: Intent,
        verification_method: str | None,
        events: list[AuditEvent],
        status: GateStatus,
        reason_code: str,
        evidence: StateEvidence | None = None,
        *,
        record: bool = True,
    ) -> ShadowAssessment:
        if status == GateStatus.PASS:
            result = ShadowResult.WOULD_DISPATCH
        elif status == GateStatus.UNAVAILABLE:
            result = ShadowResult.INDETERMINATE
        else:
            result = ShadowResult.WOULD_BLOCK
        if record:
            self._registry.record(intent.operation_id)
        events.append(
            self._event(
                "finished",
                intent,
                verification_method,
                gate_status=status,
                reason_code=reason_code,
                shadow_result=result,
            )
        )
        return ShadowAssessment(
            gate=GateResult(
                status=status,
                reason_code=reason_code,
                state_observed_at=evidence.observed_at if evidence else None,
                state_quality=evidence.quality if evidence else None,
            ),
            result=result,
            audit_events=tuple(events),
        )


def _require_safe_name(name: str, value: str) -> None:
    if not isinstance(value, str) or _SAFE_NAME.fullmatch(value) is None:
        raise ValueError(f"{name} must be a safe alias")


def _require_aware(name: str, value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
