"""Offline operational failure drills for the HESTIA v1 release gate.

These drills deliberately use anonymous fixtures only.  They must not open a
production database, contact a household device, or mutate a deployed runtime.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hedp.events import (
    AsyncDeliveryQueue,
    DeliveryStatus,
    EventDeliveryHub,
    EventEnvelope,
)
from hedp.operations.execution import (
    AdapterExecutionResult,
    Authorization,
    EvidenceQuality,
    ExecutionCapability,
    ExecutionCoordinator,
    ExecutionMode,
    ExecutionOutcome,
    Intent,
    StateEvidence,
    function_port,
)
from hedp.operations.immediate import ImmediateExecutionSession, PreparedOperation


NOW = datetime(2026, 7, 28, 1, 0, tzinfo=timezone.utc)


def _capability() -> ExecutionCapability:
    return ExecutionCapability(
        target_alias="fixture-light",
        capability="brightness-set",
        control_owner="hestia",
        allowed_desired_states=(),
        maximum_state_age=timedelta(seconds=30),
        desired_state_validator=lambda value: (
            type(value) is int and 0 <= value <= 100
        ),
    )


def _intent(
    *,
    operation_id: str = "fixture-operation",
    desired_state: object = 50,
) -> Intent:
    return Intent(
        operation_id=operation_id,
        requested_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(seconds=30),
        requester="fixture-user",
        reason="offline operational drill",
        target_alias="fixture-light",
        capability="brightness-set",
        desired_state=desired_state,
        priority=1,
        control_owner="hestia",
        correlation_id=f"fixture-correlation-{operation_id}",
    )


def _authorization(
    *,
    operation_id: str = "fixture-operation",
    desired_state: object = 50,
) -> Authorization:
    return Authorization(
        operation_id=operation_id,
        requester="fixture-user",
        target_alias="fixture-light",
        capability="brightness-set",
        desired_state=desired_state,
        granted_at=NOW - timedelta(seconds=10),
        expires_at=NOW + timedelta(seconds=30),
    )


def _evidence(
    *,
    observed_at: datetime = NOW - timedelta(seconds=1),
    quality: EvidenceQuality = EvidenceQuality.GOOD,
) -> StateEvidence:
    return StateEvidence(
        target_alias="fixture-light",
        capability="brightness-set",
        observed_at=observed_at,
        quality=quality,
        current_state=25,
    )


def _operation(
    *,
    operation_id: str = "fixture-operation",
    desired_state: object = 50,
) -> PreparedOperation:
    return PreparedOperation(
        _intent(operation_id=operation_id, desired_state=desired_state),
        _evidence(),
        _authorization(
            operation_id=operation_id,
            desired_state=desired_state,
        ),
        NOW,
    )


def _coordinator(calls: list[str]) -> ExecutionCoordinator:
    def dispatch(value: Intent) -> AdapterExecutionResult:
        calls.append(value.operation_id)
        return AdapterExecutionResult(
            "accepted",
            "matched",
            ExecutionOutcome.COMPLETED,
        )

    return ExecutionCoordinator(
        (_capability(),),
        {
            ("fixture-light", "brightness-set"): function_port(
                dispatch,
                test_fixture=True,
            )
        },
    )


def _event(event_id: str, sequence: int) -> EventEnvelope[str]:
    return EventEnvelope(
        source_alias="fixture-source",
        event_id=event_id,
        sequence=sequence,
        observed_at=NOW,
        payload="anonymous",
        important=True,
    )


def test_shutdown_and_restart_do_not_replay_pending_intent() -> None:
    """An unsent debounced command is discarded and absent after restart."""

    calls: list[str] = []
    first = ImmediateExecutionSession(
        _coordinator(calls),
        mode=ExecutionMode.FIXTURE,
        debounce_seconds=0.2,
    )
    first.submit_latest(_operation())
    first.close(discard_pending=True)

    restarted = ImmediateExecutionSession(
        _coordinator(calls),
        mode=ExecutionMode.FIXTURE,
        debounce_seconds=0.02,
    )
    assert restarted.wait_idle()
    restarted.close()

    assert calls == []


def test_storage_failure_is_bounded_and_does_not_cancel_control() -> None:
    """A failing database-like sink stays off the immediate control path."""

    control_calls: list[str] = []
    storage = AsyncDeliveryQueue[str]("storage", capacity=1, max_attempts=2)
    hub = EventDeliveryHub(
        realtime_consumers={
            "control": lambda event: control_calls.append(event.event_id)
        },
        async_lanes={"storage": storage},
    )
    try:
        receipts = hub.publish(_event("storage-failure", 1))
        retry = storage.deliver_one(
            lambda _: (_ for _ in ()).throw(RuntimeError("fixture storage offline"))
        )
        exhausted = storage.deliver_one(
            lambda _: (_ for _ in ()).throw(RuntimeError("fixture storage offline"))
        )
    finally:
        hub.close()

    assert [item.status for item in receipts] == [
        DeliveryStatus.DELIVERED,
        DeliveryStatus.QUEUED,
    ]
    assert retry.status is DeliveryStatus.RETRY_QUEUED
    assert exhausted.status is DeliveryStatus.RETRIES_EXHAUSTED
    assert control_calls == ["storage-failure"]


def test_communication_loss_fails_closed_before_dispatch() -> None:
    """Missing or stale observation never reaches a device transport."""

    calls: list[str] = []
    coordinator = _coordinator(calls)
    stale = coordinator.execute(
        _intent(operation_id="stale-observation"),
        evidence=_evidence(observed_at=NOW - timedelta(minutes=1)),
        authorization=_authorization(operation_id="stale-observation"),
        evaluated_at=NOW,
        mode=ExecutionMode.FIXTURE,
    )
    missing = coordinator.execute(
        _intent(operation_id="missing-observation"),
        evidence=None,
        authorization=_authorization(operation_id="missing-observation"),
        evaluated_at=NOW,
        mode=ExecutionMode.FIXTURE,
    )

    assert stale.gate.reason_code == "state_not_fresh"
    assert missing.gate.reason_code == "state_missing"
    assert stale.dispatch_attempted is False
    assert missing.dispatch_attempted is False
    assert calls == []


def test_unexpected_schema_fails_closed_before_dispatch() -> None:
    """Unexpected value shape is explicit and is never coerced or sent."""

    calls: list[str] = []
    coordinator = _coordinator(calls)
    result = coordinator.execute(
        _intent(
            operation_id="unexpected-schema",
            desired_state={"brightness": "unknown"},
        ),
        evidence=_evidence(),
        authorization=_authorization(
            operation_id="unexpected-schema",
            desired_state={"brightness": "unknown"},
        ),
        evaluated_at=NOW,
        mode=ExecutionMode.FIXTURE,
    )

    assert result.gate.reason_code == "desired_state_invalid"
    assert result.dispatch_attempted is False
    assert calls == []
