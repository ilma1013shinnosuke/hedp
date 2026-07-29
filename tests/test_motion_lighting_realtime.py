from datetime import datetime, timedelta, timezone

from hedp.adapters.smartledz.operation import (
    DryRunSupport,
    SmartLedzCapabilitySnapshot,
    SmartLedzDryRunPlanner,
)
from hedp.adapters.switchbot.secondary_state import (
    DetectionState,
    RegistrationStatus,
    SecondaryDeviceKind,
    SecondaryDeviceObservation,
    SecondaryField,
    SecondaryFieldObservation,
    SecondarySource,
)
from hedp.events import AsyncDeliveryQueue, DeliveryStatus, EventDeliveryHub, EventEnvelope
from hedp.intelligence.motion_lighting import (
    LightingSelection,
    LightingSelectionKind,
    MotionLightingAutomation,
    MotionLightingDecision,
    MotionLightingReason,
    MotionLightingRule,
)
from hedp.observations import ObservedValue, Quality
from hedp.operations.motion_lighting_realtime import (
    MotionLightingRealtimeConsumer,
    plan_smartledz_motion_decision,
)


def test_switchbot_motion_reaches_decision_before_storage_is_drained() -> None:
    current = iter((10.0, 40.0))
    decisions = []
    rule = MotionLightingRule(
        "entrance-motion-light",
        "entrance-motion",
        30,
        LightingSelection(
            LightingSelectionKind.SCENE, "entrance", "motion-on"
        ),
        LightingSelection(
            LightingSelectionKind.SCHEDULE, "entrance", "normal-schedule"
        ),
    )
    consumer = MotionLightingRealtimeConsumer(
        MotionLightingAutomation(rule),
        decisions.append,
        clock=lambda: next(current),
    )
    storage = AsyncDeliveryQueue[SecondaryDeviceObservation](
        "storage", capacity=4
    )
    now = datetime(2026, 7, 27, tzinfo=timezone.utc)
    observation = SecondaryDeviceObservation(
        target_alias="entrance-motion",
        kind=SecondaryDeviceKind.MOTION_SENSOR,
        registration_status=RegistrationStatus.OBSERVABLE,
        source=SecondarySource.BLE_EVENT,
        observed_at=now,
        received_at=now,
        fields=(
            SecondaryFieldObservation(
                SecondaryField.MOTION,
                ObservedValue(DetectionState.DETECTED, Quality.GOOD),
            ),
        ),
        quality=Quality.GOOD,
    )
    event = EventEnvelope(
        source_alias="switchbot-motion",
        event_id="motion-1",
        sequence=1,
        observed_at=now,
        payload=observation,
        important=True,
    )
    hub = EventDeliveryHub(
        realtime_consumers={"motion-lighting": consumer},
        async_lanes={"storage": storage},
    )

    receipts = hub.publish(event)
    assert decisions[0].reason is MotionLightingReason.FIRST_DETECTION
    assert len(storage) == 1
    assert receipts[0].status is DeliveryStatus.DELIVERED
    assert receipts[1].status is DeliveryStatus.QUEUED

    consumer.tick()
    assert decisions[1].reason is MotionLightingReason.HOLD_EXPIRED
    hub.close()


def test_scene_and_schedule_decisions_use_existing_smartledz_safety() -> None:
    observed_at = datetime(2026, 7, 27, tzinfo=timezone.utc)
    planner = SmartLedzDryRunPlanner(
        gateway_id=1,
        group_aliases={"entrance": 2},
        scene_aliases={"motion-on": 3},
        schedule_aliases={"normal-schedule": 4},
        capability_snapshot=SmartLedzCapabilitySnapshot(
            gateway_id=1,
            observed_at=observed_at,
            max_age=timedelta(seconds=60),
            quality=Quality.GOOD,
            scene_run_supported=True,
            scene_readback_supported=True,
            group_scenes={"entrance": frozenset({"motion-on"})},
        ),
        clock=lambda: observed_at,
    )
    rule = MotionLightingRule(
        "entrance-motion-light",
        "entrance-motion",
        30,
        LightingSelection(
            LightingSelectionKind.SCENE, "entrance", "motion-on"
        ),
        LightingSelection(
            LightingSelectionKind.SCHEDULE, "entrance", "normal-schedule"
        ),
    )
    start = MotionLightingDecision(
        rule.rule_alias,
        rule.on_detected,
        MotionLightingReason.FIRST_DETECTION,
        "motion-1",
    )
    end = MotionLightingDecision(
        rule.rule_alias,
        rule.on_timeout,
        MotionLightingReason.HOLD_EXPIRED,
        "timeout-1",
    )

    assert plan_smartledz_motion_decision(start, planner).support is DryRunSupport.VERIFIED
    stopped = plan_smartledz_motion_decision(end, planner)
    assert stopped.support is DryRunSupport.UNSUPPORTED
    assert stopped.reason == "schedule_selection_schema_and_readback_unverified"
