from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from hedp.operations.execution import (
    AdapterExecutionResult,
    Authorization,
    ExecutionCapability,
    ExecutionCoordinator,
    ExecutionMode,
    ExecutionOutcome,
    GateStatus,
    Intent,
    OperationRegistry,
    StateEvidence,
    EvidenceQuality,
    function_port,
)


NOW = datetime(2026, 7, 26, 2, 0, tzinfo=timezone.utc)


def capability(**changes):
    values = {
        "target_alias": "fixture-lock",
        "capability": "lock-position-set",
        "control_owner": "sumicore",
        "allowed_desired_states": ("lock", "unlock"),
        "maximum_state_age": timedelta(seconds=30),
    }
    values.update(changes)
    return ExecutionCapability(**values)


def intent(**changes):
    values = {
        "operation_id": "operation-1",
        "requested_at": NOW - timedelta(seconds=2),
        "expires_at": NOW + timedelta(seconds=30),
        "requester": "fixture-user",
        "reason": "anonymous fixture",
        "target_alias": "fixture-lock",
        "capability": "lock-position-set",
        "desired_state": "lock",
        "priority": 1,
        "control_owner": "sumicore",
        "correlation_id": "decision-1",
    }
    values.update(changes)
    return Intent(**values)


def evidence(**changes):
    values = {
        "target_alias": "fixture-lock",
        "capability": "lock-position-set",
        "observed_at": NOW - timedelta(seconds=5),
        "quality": EvidenceQuality.GOOD,
        "current_state": "unlock",
    }
    values.update(changes)
    return StateEvidence(**values)


def authorization(**changes):
    values = {
        "operation_id": "operation-1",
        "requester": "fixture-user",
        "target_alias": "fixture-lock",
        "capability": "lock-position-set",
        "desired_state": "lock",
        "granted_at": NOW - timedelta(minutes=1),
        "expires_at": NOW + timedelta(minutes=1),
    }
    values.update(changes)
    return Authorization(**values)


def test_shadow_mode_never_calls_port():
    calls = []
    port = function_port(
        lambda value: calls.append(value),
        test_fixture=True,
    )
    coordinator = ExecutionCoordinator(
        (capability(),),
        {("fixture-lock", "lock-position-set"): port},
    )

    result = coordinator.execute(
        intent(),
        evidence=evidence(),
        authorization=authorization(),
        evaluated_at=NOW,
    )

    assert result.outcome is ExecutionOutcome.WOULD_DISPATCH
    assert result.dispatch_attempted is False
    assert calls == []


def test_fixture_dispatch_is_called_exactly_once_and_completed():
    calls = []

    def dispatch(value):
        calls.append(value.operation_id)
        return AdapterExecutionResult("accepted", "matched", ExecutionOutcome.COMPLETED)

    coordinator = ExecutionCoordinator(
        (capability(),),
        {
            ("fixture-lock", "lock-position-set"): function_port(
                dispatch,
                test_fixture=True,
            )
        },
    )
    result = coordinator.execute(
        intent(),
        evidence=evidence(),
        authorization=authorization(),
        evaluated_at=NOW,
        mode=ExecutionMode.FIXTURE,
    )

    assert calls == ["operation-1"]
    assert result.outcome is ExecutionOutcome.COMPLETED
    assert result.dispatch_attempted is True
    assert [event.phase for event in result.audit_events] == [
        "received",
        "gate_checking",
        "ready",
        "dispatching",
        "verifying",
        "finished",
    ]


def test_fixture_mode_rejects_unmarked_port():
    class UnmarkedPort:
        def execute(self, _):
            raise AssertionError("must not be called")

    coordinator = ExecutionCoordinator(
        (capability(),),
        {("fixture-lock", "lock-position-set"): UnmarkedPort()},
    )
    result = coordinator.execute(
        intent(),
        evidence=evidence(),
        authorization=authorization(),
        evaluated_at=NOW,
        mode=ExecutionMode.FIXTURE,
    )

    assert result.gate.reason_code == "fixture_port_required"
    assert result.dispatch_attempted is False


def test_live_mode_requires_explicit_production_port_marker():
    class UnmarkedPort:
        def execute(self, _):
            raise AssertionError("must not be called")

    coordinator = ExecutionCoordinator(
        (capability(),),
        {("fixture-lock", "lock-position-set"): UnmarkedPort()},
    )
    result = coordinator.execute(
        intent(),
        evidence=evidence(),
        authorization=authorization(),
        evaluated_at=NOW,
        mode=ExecutionMode.LIVE,
    )

    assert result.gate.reason_code == "production_port_required"
    assert result.dispatch_attempted is False


def test_callable_port_requires_explicit_test_fixture_acknowledgement():
    with pytest.raises(PermissionError, match="test-fixture-only"):
        function_port(
            lambda _: AdapterExecutionResult(
                "accepted",
                "matched",
                ExecutionOutcome.COMPLETED,
            )
        )


def test_state_evidence_is_bound_to_target_and_capability():
    coordinator = ExecutionCoordinator((capability(),))
    wrong_target = coordinator.execute(
        intent(),
        evidence=evidence(target_alias="other-lock"),
        authorization=authorization(),
        evaluated_at=NOW,
    )
    wrong_capability = coordinator.execute(
        intent(),
        evidence=evidence(capability="other-capability"),
        authorization=authorization(),
        evaluated_at=NOW,
    )

    assert wrong_target.gate.reason_code == "state_scope_mismatch"
    assert wrong_capability.gate.reason_code == "state_scope_mismatch"


def test_missing_or_wrong_authorization_blocks_without_dispatch():
    calls = []
    coordinator = ExecutionCoordinator(
        (capability(),),
        {
            ("fixture-lock", "lock-position-set"): function_port(
                lambda value: calls.append(value),
                test_fixture=True,
            )
        },
    )
    missing = coordinator.execute(
        intent(operation_id="missing-auth"),
        evidence=evidence(capability="temperature-set"),
        authorization=None,
        evaluated_at=NOW,
        mode=ExecutionMode.FIXTURE,
    )
    wrong = coordinator.execute(
        intent(operation_id="wrong-auth"),
        evidence=evidence(),
        authorization=authorization(
            operation_id="wrong-auth",
            target_alias="other-lock",
        ),
        evaluated_at=NOW,
        mode=ExecutionMode.FIXTURE,
    )

    assert missing.gate.reason_code == "authorization_missing"
    assert wrong.gate.reason_code == "authorization_scope_mismatch"
    assert calls == []


def test_authorization_is_bound_to_exact_operation_requester_and_state():
    coordinator = ExecutionCoordinator((capability(),))
    wrong_operation = coordinator.execute(
        intent(operation_id="different-operation"),
        evidence=evidence(),
        authorization=authorization(),
        evaluated_at=NOW,
        mode=ExecutionMode.FIXTURE,
    )
    wrong_requester = coordinator.execute(
        intent(requester="different-requester"),
        evidence=evidence(),
        authorization=authorization(),
        evaluated_at=NOW,
        mode=ExecutionMode.FIXTURE,
    )
    wrong_state = coordinator.execute(
        intent(desired_state="unlock"),
        evidence=evidence(),
        authorization=authorization(),
        evaluated_at=NOW,
        mode=ExecutionMode.FIXTURE,
    )

    assert wrong_operation.gate.reason_code == "authorization_scope_mismatch"
    assert wrong_requester.gate.reason_code == "authorization_scope_mismatch"
    assert wrong_state.gate.reason_code == "authorization_scope_mismatch"


def test_expiry_stale_state_and_manual_override_stop_before_port():
    coordinator = ExecutionCoordinator((capability(),))
    expired = coordinator.execute(
        intent(expires_at=NOW),
        evidence=evidence(),
        authorization=authorization(),
        evaluated_at=NOW,
    )
    stale = coordinator.execute(
        intent(operation_id="stale"),
        evidence=evidence(observed_at=NOW - timedelta(minutes=1)),
        authorization=authorization(operation_id="stale"),
        evaluated_at=NOW,
    )
    manual = coordinator.execute(
        intent(operation_id="manual"),
        evidence=evidence(manual_override_at=NOW - timedelta(minutes=1)),
        authorization=authorization(operation_id="manual"),
        evaluated_at=NOW,
        manual_override_cooldown=timedelta(hours=3),
    )

    assert expired.gate.status is GateStatus.EXPIRED
    assert stale.gate.reason_code == "state_not_fresh"
    assert manual.gate.reason_code == "manual_override_active"


def test_adapter_exception_is_unknown_and_never_retried():
    calls = []

    def fail(value):
        calls.append(value.operation_id)
        raise TimeoutError

    coordinator = ExecutionCoordinator(
        (capability(),),
        {
            ("fixture-lock", "lock-position-set"): function_port(
                fail,
                test_fixture=True,
            )
        },
    )
    result = coordinator.execute(
        intent(),
        evidence=evidence(),
        authorization=authorization(),
        evaluated_at=NOW,
        mode=ExecutionMode.FIXTURE,
    )

    assert calls == ["operation-1"]
    assert result.outcome is ExecutionOutcome.UNKNOWN
    assert result.dispatch_attempted is True


def test_contradictory_adapter_result_is_unknown():
    coordinator = ExecutionCoordinator(
        (capability(),),
        {
            ("fixture-lock", "lock-position-set"): function_port(
                lambda _: AdapterExecutionResult(
                    "timeout",
                    "unavailable",
                    ExecutionOutcome.COMPLETED,
                ),
                test_fixture=True,
            )
        },
    )
    result = coordinator.execute(
        intent(),
        evidence=evidence(),
        authorization=authorization(),
        evaluated_at=NOW,
        mode=ExecutionMode.FIXTURE,
    )

    assert result.outcome is ExecutionOutcome.UNKNOWN
    assert result.adapter_result is None
    assert result.audit_events[-1].reason_code == "adapter_result_invalid"


def test_malformed_adapter_result_is_unknown():
    coordinator = ExecutionCoordinator(
        (capability(),),
        {
            ("fixture-lock", "lock-position-set"): function_port(
                lambda _: object(),
                test_fixture=True,
            )
        },
    )
    result = coordinator.execute(
        intent(),
        evidence=evidence(),
        authorization=authorization(),
        evaluated_at=NOW,
        mode=ExecutionMode.FIXTURE,
    )

    assert result.outcome is ExecutionOutcome.UNKNOWN
    assert result.adapter_result is None


def test_duplicate_fixture_dispatch_is_blocked_after_first_claim():
    coordinator = ExecutionCoordinator(
        (capability(),),
        {
            ("fixture-lock", "lock-position-set"): function_port(
                lambda _: AdapterExecutionResult(
                    "accepted", "matched", ExecutionOutcome.COMPLETED
                ),
                test_fixture=True,
            )
        },
    )
    first = coordinator.execute(
        intent(),
        evidence=evidence(),
        authorization=authorization(),
        evaluated_at=NOW,
        mode=ExecutionMode.FIXTURE,
    )
    duplicate = coordinator.execute(
        intent(),
        evidence=evidence(),
        authorization=authorization(),
        evaluated_at=NOW,
        mode=ExecutionMode.FIXTURE,
    )

    assert first.outcome is ExecutionOutcome.COMPLETED
    assert duplicate.gate.reason_code == "duplicate_operation_id"


def test_shadow_assessment_does_not_consume_dispatch_operation_id():
    calls = []
    coordinator = ExecutionCoordinator(
        (capability(),),
        {
            ("fixture-lock", "lock-position-set"): function_port(
                lambda value: (
                    calls.append(value.operation_id)
                    or AdapterExecutionResult(
                        "accepted", "matched", ExecutionOutcome.COMPLETED
                    )
                ),
                test_fixture=True,
            )
        },
    )

    shadow = coordinator.execute(
        intent(),
        evidence=evidence(),
        authorization=authorization(),
        evaluated_at=NOW,
    )
    fixture = coordinator.execute(
        intent(),
        evidence=evidence(),
        authorization=authorization(),
        evaluated_at=NOW,
        mode=ExecutionMode.FIXTURE,
    )

    assert shadow.outcome is ExecutionOutcome.WOULD_DISPATCH
    assert fixture.outcome is ExecutionOutcome.COMPLETED
    assert calls == ["operation-1"]


def test_invalid_execution_mode_fails_closed_without_dispatch():
    calls = []
    coordinator = ExecutionCoordinator(
        (capability(),),
        {
            ("fixture-lock", "lock-position-set"): function_port(
                lambda value: calls.append(value),
                test_fixture=True,
            )
        },
    )

    result = coordinator.execute(
        intent(),
        evidence=evidence(),
        authorization=authorization(),
        evaluated_at=NOW,
        mode="fixture",  # type: ignore[arg-type]
    )

    assert result.gate.reason_code == "execution_mode_invalid"
    assert result.dispatch_attempted is False
    assert calls == []


def test_capability_validator_accepts_bounded_values_and_rejects_others():
    bounded = capability(
        capability="temperature-set",
        allowed_desired_states=(),
        desired_state_validator=lambda value: type(value) is int and 16 <= value <= 30,
    )
    coordinator = ExecutionCoordinator((bounded,))

    accepted = coordinator.execute(
        intent(
            capability="temperature-set",
            desired_state=24,
        ),
        evidence=evidence(capability="temperature-set"),
        authorization=authorization(
            capability="temperature-set",
            desired_state=24,
        ),
        evaluated_at=NOW,
    )
    rejected = coordinator.execute(
        intent(
            operation_id="operation-2",
            capability="temperature-set",
            desired_state=31,
        ),
        evidence=evidence(capability="temperature-set"),
        authorization=authorization(
            operation_id="operation-2",
            capability="temperature-set",
            desired_state=31,
        ),
        evaluated_at=NOW,
    )

    assert accepted.outcome is ExecutionOutcome.WOULD_DISPATCH
    assert rejected.gate.reason_code == "desired_state_invalid"


def test_capability_validator_failure_blocks_without_dispatch():
    calls = []

    def broken_validator(_):
        raise RuntimeError("fixture validator failure")

    bounded = capability(
        capability="temperature-set",
        allowed_desired_states=(),
        desired_state_validator=broken_validator,
    )
    coordinator = ExecutionCoordinator(
        (bounded,),
        {
            ("fixture-lock", "temperature-set"): function_port(
                lambda value: calls.append(value),
                test_fixture=True,
            )
        },
    )

    result = coordinator.execute(
        intent(capability="temperature-set", desired_state=24),
        evidence=evidence(),
        authorization=authorization(
            capability="temperature-set",
            desired_state=24,
        ),
        evaluated_at=NOW,
        mode=ExecutionMode.FIXTURE,
    )

    assert result.gate.reason_code == "desired_state_invalid"
    assert result.dispatch_attempted is False
    assert calls == []


def test_registry_claim_is_atomic():
    registry = OperationRegistry()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: registry.claim("same-operation"), range(20)))

    assert results.count(True) == 1
    assert results.count(False) == 19


def test_audit_does_not_copy_reason_state_or_authorization():
    coordinator = ExecutionCoordinator((capability(),))
    result = coordinator.execute(
        intent(reason="sensitive reason"),
        evidence=evidence(current_state={"secret": "not-copied"}),
        authorization=authorization(),
        evaluated_at=NOW,
    )
    payload = str([event.to_dict() for event in result.audit_events])

    assert "sensitive" not in payload
    assert "secret" not in payload
