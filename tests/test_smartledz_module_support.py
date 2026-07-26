from datetime import datetime, timedelta, timezone

import pytest

from hedp.adapters.smartledz import (
    NotificationDisposition,
    ObservationTime,
    Quality,
    SmartLedzNotificationNormalizer,
    normalize_device_state,
)
from hedp.adapters.smartledz.operation import (
    DryRunSupport,
    SmartLedzCapabilitySnapshot,
    SmartLedzDryRunPlanner,
    SmartLedzOperation,
)


TIME = ObservationTime(
    "2026-07-26T10:00:00+09:00",
    "2026-07-26T10:00:01+09:00",
)
NOW = datetime(2026, 7, 26, 1, tzinfo=timezone.utc)


def planner(
    snapshot: SmartLedzCapabilitySnapshot | None = None,
) -> SmartLedzDryRunPlanner:
    if snapshot is None:
        snapshot = SmartLedzCapabilitySnapshot(
            gateway_id=11,
            group_scenes={"living": frozenset({"night"})},
            observed_at=NOW - timedelta(seconds=10),
            max_age=timedelta(minutes=5),
            quality=Quality.GOOD,
            scene_run_supported=True,
            scene_readback_supported=True,
        )
    return SmartLedzDryRunPlanner(
        gateway_id=11,
        group_aliases={"living": 101},
        scene_aliases={"night": 201},
        schedule_aliases={"weekday": 301},
        capability_snapshot=snapshot,
        clock=lambda: NOW,
    )


def test_individual_device_state_is_explicitly_unsupported_without_schema() -> None:
    state = normalize_device_state(
        {"ErrorCode": 0, "Data": {"unknown": True}},
        target_ref="living-main",
        time=TIME,
    )

    assert state.quality is Quality.UNKNOWN
    assert state.reason == "device_state_schema_unverified"
    assert state.power is None
    assert state.brightness_pct is None
    assert "Data" not in repr(state)


def test_scene_run_has_verified_typed_dry_run_shape() -> None:
    plan = planner().scene_run(group_alias="living", scene_alias="night")

    assert plan.operation is SmartLedzOperation.SCENE_RUN
    assert plan.support is DryRunSupport.VERIFIED
    assert plan.would_dispatch
    assert plan.command == {
        "c": "GroupSceneRun",
        "gateway_id": 11,
        "group_id": 101,
        "scene_id": 201,
    }
    assert "101" not in repr(plan)
    assert "201" not in repr(plan)


def test_schedule_selection_remains_typed_but_explicitly_unsupported() -> None:
    plan = planner().schedule_select(
        group_alias="living",
        schedule_alias="weekday",
    )

    assert plan.operation is SmartLedzOperation.SCHEDULE_SELECT
    assert plan.support is DryRunSupport.UNSUPPORTED
    assert not plan.would_dispatch
    assert plan.command is None
    assert "unverified" in plan.reason


def test_unknown_alias_is_blocked_without_constructing_a_command() -> None:
    with pytest.raises(PermissionError, match="scene alias"):
        planner().scene_run(group_alias="living", scene_alias="private-id")


def test_scene_run_without_runtime_evidence_is_indeterminate() -> None:
    plan = SmartLedzDryRunPlanner(
        gateway_id=11,
        group_aliases={"living": 101},
        scene_aliases={"night": 201},
        schedule_aliases={},
        clock=lambda: NOW,
    ).scene_run(group_alias="living", scene_alias="night")

    assert plan.support is DryRunSupport.INDETERMINATE
    assert not plan.would_dispatch
    assert plan.command is None
    assert plan.reason == "runtime_capability_missing"


def test_scene_must_belong_to_group_in_fresh_readback() -> None:
    snapshot = SmartLedzCapabilitySnapshot(
        gateway_id=11,
        group_scenes={"living": frozenset()},
        observed_at=NOW,
        max_age=timedelta(minutes=1),
        quality=Quality.GOOD,
        scene_run_supported=True,
        scene_readback_supported=True,
    )

    plan = planner(snapshot).scene_run(group_alias="living", scene_alias="night")

    assert plan.support is DryRunSupport.UNSUPPORTED
    assert not plan.would_dispatch
    assert plan.reason == "scene_not_observed_for_group"


def test_stale_or_unverifiable_scene_readback_is_indeterminate() -> None:
    stale = SmartLedzCapabilitySnapshot(
        gateway_id=11,
        group_scenes={"living": frozenset({"night"})},
        observed_at=NOW - timedelta(minutes=2),
        max_age=timedelta(minutes=1),
        quality=Quality.GOOD,
        scene_run_supported=True,
        scene_readback_supported=True,
    )
    no_readback = SmartLedzCapabilitySnapshot(
        gateway_id=11,
        group_scenes={"living": frozenset({"night"})},
        observed_at=NOW,
        max_age=timedelta(minutes=1),
        quality=Quality.GOOD,
        scene_run_supported=True,
        scene_readback_supported=False,
    )

    assert (
        planner(stale).scene_run(group_alias="living", scene_alias="night").reason
        == "runtime_capability_stale"
    )
    assert (
        planner(no_readback).scene_run(group_alias="living", scene_alias="night").reason
        == "scene_readback_not_supported"
    )


def test_notifications_are_finite_deduplicated_and_force_resync() -> None:
    normalizer = SmartLedzNotificationNormalizer(maximum_fingerprints=2)
    normalizer.mark_resynchronized()

    first = normalizer.normalize({"event": "changed", "device_id": 123})
    duplicate = normalizer.normalize({"device_id": 123, "event": "changed"})
    normalizer.normalize({"event": 2})
    normalizer.normalize({"event": 3})
    evicted = normalizer.normalize({"event": "changed", "device_id": 123})

    assert first.disposition is NotificationDisposition.NEW_UNSUPPORTED
    assert first.safe_fields == ("event",)
    assert first.redacted_field_count == 1
    assert first.resync_required
    assert duplicate.disposition is NotificationDisposition.DUPLICATE
    assert normalizer.retained_fingerprint_count == 2
    assert evicted.disposition is NotificationDisposition.NEW_UNSUPPORTED


def test_invalid_notification_never_becomes_an_event() -> None:
    result = SmartLedzNotificationNormalizer().normalize(datetime(2026, 7, 26))

    assert result.disposition is NotificationDisposition.INVALID
    assert result.fingerprint is None
    assert result.resync_required


@pytest.mark.parametrize(
    ("normalizer", "payload", "reason"),
    [
        (
            SmartLedzNotificationNormalizer(maximum_payload_bytes=256),
            {"event": "x" * 300},
            "notification_byte_limit_exceeded",
        ),
        (
            SmartLedzNotificationNormalizer(maximum_depth=2),
            {"event": {"nested": {"too": "deep"}}},
            "notification_depth_limit_exceeded",
        ),
        (
            SmartLedzNotificationNormalizer(maximum_fields=2),
            {"event": 1, "type": 2, "status": 3},
            "notification_field_limit_exceeded",
        ),
    ],
)
def test_notification_bounds_fail_before_fingerprinting(
    normalizer: SmartLedzNotificationNormalizer,
    payload: object,
    reason: str,
) -> None:
    result = normalizer.normalize(payload)

    assert result.disposition is NotificationDisposition.INVALID
    assert result.fingerprint is None
    assert result.reason == reason


def test_safe_fields_are_allowlisted_not_inferred_from_unknown_keys() -> None:
    result = SmartLedzNotificationNormalizer().normalize(
        {
            "event": "changed",
            "person@example.com": "private",
            "householdLabel": "private",
        }
    )

    assert result.safe_fields == ("event",)
    assert result.redacted_field_count == 2
