from datetime import datetime, timedelta, timezone

import pytest

from hedp.operations.shadow_execution import (
    CapabilityDescriptor,
    EvidenceQuality,
    GateStatus,
    Intent,
    ShadowExecutionGate,
    ShadowOperationRegistry,
    ShadowResult,
    StateEvidence,
)


NOW = datetime(2026, 7, 25, 1, 0, tzinfo=timezone.utc)


def capability() -> CapabilityDescriptor:
    return CapabilityDescriptor(
        target_alias="test-light",
        capability="set-power",
        control_owner="sumicore",
        allowed_desired_states=(True, False),
        verification_method="read-back",
        maximum_state_age=timedelta(seconds=30),
    )


def intent(**overrides: object) -> Intent:
    values = {
        "operation_id": "operation-1",
        "requested_at": NOW - timedelta(seconds=5),
        "expires_at": NOW + timedelta(seconds=30),
        "requester": "test-rule",
        "reason": "anonymous fixture",
        "target_alias": "test-light",
        "capability": "set-power",
        "desired_state": False,
        "priority": 1,
        "control_owner": "sumicore",
        "correlation_id": "decision-1",
    }
    values.update(overrides)
    return Intent(**values)


def evidence(**overrides: object) -> StateEvidence:
    values = {
        "observed_at": NOW - timedelta(seconds=10),
        "quality": EvidenceQuality.GOOD,
        "current_state": True,
    }
    values.update(overrides)
    return StateEvidence(**values)


def test_valid_intent_would_dispatch_without_side_effects() -> None:
    result = ShadowExecutionGate((capability(),)).assess(
        intent(), evidence=evidence(), evaluated_at=NOW
    )

    assert result.gate.status == GateStatus.PASS
    assert result.result == ShadowResult.WOULD_DISPATCH
    assert result.dispatch_attempted is False
    assert [item.phase for item in result.audit_events] == [
        "received",
        "gate_checking",
        "finished",
    ]
    assert all(item.dispatch_attempted is False for item in result.audit_events)
    assert "completed" not in str([item.to_dict() for item in result.audit_events])
    assert "accepted" not in str([item.to_dict() for item in result.audit_events])


@pytest.mark.parametrize(
    ("changes", "status", "reason"),
    [
        (
            {"expires_at": NOW - timedelta(seconds=1)},
            GateStatus.EXPIRED,
            "intent_expired",
        ),
        (
            {"target_alias": "another-light"},
            GateStatus.BLOCKED,
            "target_mismatch",
        ),
        (
            {"capability": "unknown-action"},
            GateStatus.BLOCKED,
            "unknown_capability",
        ),
        (
            {"control_owner": "equipment"},
            GateStatus.BLOCKED,
            "owner_mismatch",
        ),
        (
            {"desired_state": "toggle"},
            GateStatus.BLOCKED,
            "desired_state_invalid",
        ),
        (
            {"desired_state": 0},
            GateStatus.BLOCKED,
            "desired_state_invalid",
        ),
        (
            {
                "requested_at": NOW + timedelta(seconds=1),
                "expires_at": NOW + timedelta(seconds=30),
            },
            GateStatus.BLOCKED,
            "request_time_invalid",
        ),
    ],
)
def test_blocking_intent_conditions(
    changes: dict[str, object], status: GateStatus, reason: str
) -> None:
    result = ShadowExecutionGate((capability(),)).assess(
        intent(**changes), evidence=evidence(), evaluated_at=NOW
    )

    assert result.gate.status == status
    assert result.gate.reason_code == reason
    assert result.result == ShadowResult.WOULD_BLOCK


@pytest.mark.parametrize(
    "quality",
    [
        EvidenceQuality.STALE,
        EvidenceQuality.MISSING,
        EvidenceQuality.INVALID,
        EvidenceQuality.ESTIMATED,
        EvidenceQuality.UNKNOWN,
    ],
)
def test_insufficient_quality_is_indeterminate(quality: EvidenceQuality) -> None:
    result = ShadowExecutionGate((capability(),)).assess(
        intent(), evidence=evidence(quality=quality), evaluated_at=NOW
    )

    assert result.gate.status == GateStatus.UNAVAILABLE
    assert result.result == ShadowResult.INDETERMINATE


def test_missing_and_old_state_are_indeterminate() -> None:
    gate = ShadowExecutionGate((capability(),))
    missing = gate.assess(
        intent(operation_id="missing-1"), evidence=None, evaluated_at=NOW
    )
    old = gate.assess(
        intent(operation_id="old-1"),
        evidence=evidence(observed_at=NOW - timedelta(minutes=2)),
        evaluated_at=NOW,
    )
    future = gate.assess(
        intent(operation_id="future-1"),
        evidence=evidence(observed_at=NOW + timedelta(seconds=1)),
        evaluated_at=NOW,
    )

    assert missing.gate.reason_code == "state_missing"
    assert old.gate.reason_code == "state_not_fresh"
    assert future.gate.reason_code == "state_time_invalid"
    assert missing.result == old.result == future.result == ShadowResult.INDETERMINATE


def test_manual_override_and_duplicate_are_blocked() -> None:
    registry = ShadowOperationRegistry()
    gate = ShadowExecutionGate((capability(),), registry=registry)
    manual = gate.assess(
        intent(operation_id="manual-1"),
        evidence=evidence(manual_override_at=NOW - timedelta(seconds=10)),
        evaluated_at=NOW,
        manual_override_cooldown=timedelta(minutes=1),
    )
    first = gate.assess(intent(), evidence=evidence(), evaluated_at=NOW)
    duplicate = gate.assess(intent(), evidence=evidence(), evaluated_at=NOW)

    assert manual.gate.reason_code == "manual_override_active"
    assert manual.result == ShadowResult.WOULD_BLOCK
    assert first.result == ShadowResult.WOULD_DISPATCH
    assert duplicate.gate.reason_code == "duplicate_operation_id"
    assert duplicate.result == ShadowResult.WOULD_BLOCK


def test_registry_is_not_persisted_or_replayed() -> None:
    first = ShadowExecutionGate((capability(),))
    second = ShadowExecutionGate((capability(),))

    assert first.assess(intent(), evidence=evidence(), evaluated_at=NOW).result == (
        ShadowResult.WOULD_DISPATCH
    )
    assert second.assess(intent(), evidence=evidence(), evaluated_at=NOW).result == (
        ShadowResult.WOULD_DISPATCH
    )


def test_audit_output_contains_only_safe_contract_fields() -> None:
    result = ShadowExecutionGate((capability(),)).assess(
        intent(reason="must never be copied to audit"),
        evidence=evidence(current_state={"private": "not-copied"}),
        evaluated_at=NOW,
    )
    payload = result.audit_events[-1].to_dict()

    assert set(payload) == {
        "schema_version",
        "phase",
        "operation_id",
        "correlation_id",
        "target_alias",
        "control_owner",
        "verification_method",
        "gate_status",
        "reason_code",
        "shadow_result",
        "dispatch_attempted",
    }
    assert "private" not in str(payload)
    assert "must never" not in str(payload)


def test_contract_rejects_unsafe_aliases_and_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="safe alias"):
        intent(target_alias="192.0.2.1")
    with pytest.raises(ValueError, match="timezone-aware"):
        intent(requested_at=NOW.replace(tzinfo=None))
