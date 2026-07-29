from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hedp.adapters.smartledz.transition import (
    SMARTLEDZ_TRANSITION_CAPABILITY,
    ImmediateSmartLedzTransitionSession,
    SmartLedzAppearance,
    SmartLedzTransitionPlan,
    SmartLedzTransitionFixturePort,
    SmartLedzTransitionRequest,
    SmartLedzTransitionStep,
    plan_smartledz_transition,
    transition_execution_capability,
)
from hedp.operations.execution import (
    Authorization,
    ExecutionCoordinator,
    ExecutionMode,
    ExecutionOutcome,
)
from hedp.operations.shadow_execution import EvidenceQuality, Intent, StateEvidence


NOW = datetime(2026, 7, 28, 1, 0, tzinfo=timezone.utc)


class RecordingSink:
    fixture_only = True

    def __init__(self) -> None:
        self.steps: list[SmartLedzTransitionStep] = []

    def send(self, step: SmartLedzTransitionStep) -> None:
        self.steps.append(step)


def _plan(
    *,
    current: SmartLedzAppearance = SmartLedzAppearance(80, 2_700),
    target: SmartLedzAppearance = SmartLedzAppearance(30, 4_100),
) -> SmartLedzTransitionPlan:
    return plan_smartledz_transition(
        SmartLedzTransitionRequest(
            "living",
            current,
            target,
            timedelta(minutes=1),
        )
    )


def test_one_minute_plan_starts_now_and_uses_one_percent_steps() -> None:
    plan = _plan()

    assert plan.steps[0].offset == timedelta(0)
    assert plan.steps[-1].offset == timedelta(minutes=1)
    assert plan.steps[-1].appearance == SmartLedzAppearance(30, 4_100)
    brightness = [step.appearance.brightness_pct for step in plan.steps]
    assert all(abs(right - left) <= 1 for left, right in zip(brightness, brightness[1:]))
    assert len(plan.steps) <= 300


def test_identical_appearance_is_a_noop() -> None:
    appearance = SmartLedzAppearance(30, 4_100)

    assert _plan(current=appearance, target=appearance).is_noop


def test_overdue_steps_are_coalesced_and_not_replayed() -> None:
    sink = RecordingSink()
    session = ImmediateSmartLedzTransitionSession("living", sink)
    plan = _plan()

    session.submit(plan, now=100.0)
    assert sink.steps == [plan.steps[0]]
    assert session.dispatch_due(now=130.0) == 1
    assert len(sink.steps) == 2
    assert session.dispatch_due(now=160.0) == 1
    assert sink.steps[-1] == plan.steps[-1]
    assert session.pending_count == 0


def test_new_plan_replaces_unsent_steps_and_manual_cancel_discards_them() -> None:
    sink = RecordingSink()
    session = ImmediateSmartLedzTransitionSession("living", sink)
    first = _plan()
    second = _plan(
        current=SmartLedzAppearance(79, 2_700),
        target=SmartLedzAppearance(60, 3_000),
    )

    session.submit(first, now=100.0)
    session.submit(second, now=101.0)
    assert sink.steps[-1] == second.steps[0]
    session.cancel()
    assert session.dispatch_due(now=200.0) == 0


def test_common_gate_reaches_first_fixture_step_synchronously() -> None:
    plan = _plan()
    sink = RecordingSink()
    session = ImmediateSmartLedzTransitionSession("living", sink)
    port = SmartLedzTransitionFixturePort(session, clock=lambda: 10.0)
    capability = transition_execution_capability(
        target_alias="living",
        control_owner="hestia",
        maximum_state_age=timedelta(minutes=2),
    )
    coordinator = ExecutionCoordinator(
        (capability,),
        {("living", SMARTLEDZ_TRANSITION_CAPABILITY): port},
    )
    intent = Intent(
        operation_id="living-transition-1",
        requested_at=NOW,
        expires_at=NOW + timedelta(minutes=2),
        requester="local-ui",
        reason="one-minute appearance transition",
        target_alias="living",
        capability=SMARTLEDZ_TRANSITION_CAPABILITY,
        desired_state=plan,
        priority=1,
        control_owner="hestia",
        correlation_id="living-transition-request",
    )
    authorization = Authorization(
        operation_id=intent.operation_id,
        requester=intent.requester,
        target_alias=intent.target_alias,
        capability=intent.capability,
        desired_state=plan,
        granted_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=2),
    )
    evidence = StateEvidence(
        target_alias="living",
        capability=SMARTLEDZ_TRANSITION_CAPABILITY,
        observed_at=NOW,
        quality=EvidenceQuality.GOOD,
        current_state=plan.request.current,
    )

    result = coordinator.execute(
        intent,
        evidence=evidence,
        authorization=authorization,
        evaluated_at=NOW,
        mode=ExecutionMode.FIXTURE,
    )

    assert result.outcome is ExecutionOutcome.PENDING_VERIFICATION
    assert result.dispatch_attempted is True
    assert sink.steps == [plan.steps[0]]


def test_live_sink_is_rejected_until_wire_schema_is_qualified() -> None:
    class LiveSink(RecordingSink):
        fixture_only = False

    try:
        ImmediateSmartLedzTransitionSession("living", LiveSink())
    except TypeError as error:
        assert "fixture-only" in str(error)
    else:
        raise AssertionError("live sink must remain unavailable")
