from datetime import datetime, timezone

import pytest

from hedp.adapters.switchbot.secondary_state import (
    DetectionState,
    RegistrationStatus,
    SecondaryDeviceKind,
    SecondaryDeviceObservation,
    SecondaryField,
    SecondaryFieldObservation,
    SecondarySource,
)
from hedp.intelligence.motion_lighting import (
    LightingSelection,
    LightingSelectionKind,
    MotionLightingAutomation,
    MotionLightingReason,
    MotionLightingRule,
)
from hedp.observations import ObservedValue, Quality


def selection(
    kind: LightingSelectionKind = LightingSelectionKind.SCENE,
    alias: str = "motion-on",
) -> LightingSelection:
    return LightingSelection(kind, "entrance", alias)


def rule(hold_seconds: float = 900) -> MotionLightingRule:
    return MotionLightingRule(
        rule_alias="entrance-motion-light",
        sensor_alias="entrance-motion",
        hold_seconds=hold_seconds,
        on_detected=selection(),
        on_timeout=selection(LightingSelectionKind.SCHEDULE, "normal-schedule"),
    )


def observation(
    *,
    kind: SecondaryDeviceKind = SecondaryDeviceKind.MOTION_SENSOR,
    state: DetectionState = DetectionState.DETECTED,
    quality: Quality = Quality.GOOD,
    field_quality: Quality = Quality.GOOD,
    alias: str = "entrance-motion",
) -> SecondaryDeviceObservation:
    now = datetime(2026, 7, 27, tzinfo=timezone.utc)
    value = state if field_quality not in {
        Quality.MISSING,
        Quality.INVALID,
        Quality.UNKNOWN,
    } else None
    return SecondaryDeviceObservation(
        target_alias=alias,
        kind=kind,
        registration_status=RegistrationStatus.OBSERVABLE,
        source=SecondarySource.BLE_EVENT,
        observed_at=now,
        received_at=now,
        fields=(
            SecondaryFieldObservation(
                SecondaryField.MOTION,
                ObservedValue(value=value, quality=field_quality),
            ),
        ),
        quality=quality,
    )


def test_first_detection_is_immediate_and_timeout_uses_configured_action() -> None:
    automation = MotionLightingAutomation(rule())

    started = automation.process(observation(), event_id="event-1", monotonic_seconds=0)

    assert len(started) == 1
    assert started[0].reason is MotionLightingReason.FIRST_DETECTION
    assert started[0].selection.selection_alias == "motion-on"
    assert started[0].selection.capability == "scene_run"
    assert automation.deadline == 900
    assert automation.tick(899.999) == ()

    ended = automation.tick(900)
    assert len(ended) == 1
    assert ended[0].reason is MotionLightingReason.HOLD_EXPIRED
    assert ended[0].selection.selection_alias == "normal-schedule"
    assert ended[0].selection.capability == "schedule_select"
    assert automation.tick(901) == ()


def test_repeated_detection_extends_from_last_detection_without_restarting() -> None:
    automation = MotionLightingAutomation(rule())
    assert len(
        automation.process(observation(), event_id="event-1", monotonic_seconds=0)
    ) == 1

    assert (
        automation.process(
            observation(), event_id="event-2", monotonic_seconds=600
        )
        == ()
    )
    assert automation.deadline == 1500
    assert automation.tick(900) == ()
    assert len(automation.tick(1500)) == 1


def test_hold_duration_is_configurable() -> None:
    automation = MotionLightingAutomation(rule(30))
    automation.process(observation(), event_id="event-1", monotonic_seconds=10)
    assert automation.tick(39.9) == ()
    assert len(automation.tick(40)) == 1


@pytest.mark.parametrize(
    ("start_kind", "end_kind"),
    [
        (LightingSelectionKind.SCENE, LightingSelectionKind.SCENE),
        (LightingSelectionKind.SCENE, LightingSelectionKind.SCHEDULE),
        (LightingSelectionKind.SCHEDULE, LightingSelectionKind.SCENE),
        (LightingSelectionKind.SCHEDULE, LightingSelectionKind.SCHEDULE),
    ],
)
def test_start_and_end_accept_all_scene_schedule_combinations(
    start_kind: LightingSelectionKind,
    end_kind: LightingSelectionKind,
) -> None:
    configured = MotionLightingRule(
        "custom-rule",
        "entrance-motion",
        60,
        selection(start_kind, "start-selection"),
        selection(end_kind, "end-selection"),
    )
    automation = MotionLightingAutomation(configured)
    started = automation.process(
        observation(), event_id="event-1", monotonic_seconds=0
    )
    ended = automation.tick(60)
    assert started[0].selection.kind is start_kind
    assert ended[0].selection.kind is end_kind


@pytest.mark.parametrize(
    "ignored",
    [
        observation(state=DetectionState.CLEAR),
        observation(kind=SecondaryDeviceKind.PRESENCE_SENSOR_PRO),
        observation(quality=Quality.STALE),
        observation(field_quality=Quality.MISSING),
        observation(alias="other-motion"),
    ],
)
def test_non_matching_or_unusable_observations_are_ignored(
    ignored: SecondaryDeviceObservation,
) -> None:
    automation = MotionLightingAutomation(rule())
    assert automation.process(ignored, event_id="event-1", monotonic_seconds=0) == ()
    assert not automation.active


def test_duplicate_event_does_not_extend_deadline() -> None:
    automation = MotionLightingAutomation(rule(30))
    automation.process(observation(), event_id="same-event", monotonic_seconds=0)
    assert (
        automation.process(
            observation(), event_id="same-event", monotonic_seconds=20
        )
        == ()
    )
    assert automation.deadline == 30


def test_manual_override_cancels_automatic_timeout_action() -> None:
    automation = MotionLightingAutomation(rule(30))
    automation.process(observation(), event_id="event-1", monotonic_seconds=0)
    automation.manual_override()
    assert automation.tick(30) == ()


def test_new_instance_does_not_replay_old_timeout_after_restart() -> None:
    assert MotionLightingAutomation(rule()).tick(1000) == ()


def test_monotonic_time_cannot_move_backwards() -> None:
    automation = MotionLightingAutomation(rule())
    automation.tick(10)
    with pytest.raises(ValueError, match="must not move backwards"):
        automation.tick(9)


def test_json_compatible_mapping_loads_configurable_rule() -> None:
    configured = MotionLightingRule.from_mapping(
        {
            "schema": "hestia.motion-lighting-rule.v1",
            "rule_alias": "entrance-motion-light",
            "sensor_alias": "entrance-motion",
            "hold_seconds": 420,
            "on_detected": {
                "kind": "schedule",
                "target_alias": "entrance",
                "selection_alias": "welcome-schedule",
            },
            "on_timeout": {
                "kind": "scene",
                "target_alias": "entrance",
                "selection_alias": "night-scene",
            },
        }
    )
    assert configured.hold_seconds == 420
    assert configured.on_detected.kind is LightingSelectionKind.SCHEDULE
    assert configured.on_timeout.kind is LightingSelectionKind.SCENE


@pytest.mark.parametrize("hold_seconds", [0, -1, 86401, float("inf")])
def test_invalid_hold_duration_is_rejected(hold_seconds: float) -> None:
    with pytest.raises(ValueError):
        rule(hold_seconds)


def test_unsafe_alias_is_rejected() -> None:
    with pytest.raises(ValueError, match="safe opaque alias"):
        LightingSelection(LightingSelectionKind.SCENE, "private/IP", "scene")
