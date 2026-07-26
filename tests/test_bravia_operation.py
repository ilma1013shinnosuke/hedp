from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from hedp.adapters.bravia.operation import (
    BraviaAppRequest,
    BraviaCapability,
    BraviaCapabilitySnapshot,
    BraviaChannelRequest,
    BraviaDryRunOutcome,
    BraviaDryRunPlanner,
    BraviaInputRequest,
    BraviaMuteRequest,
    BraviaPowerRequest,
    BraviaPowerSetting,
    BraviaVolumeRequest,
    BraviaWakeOnLanRequest,
)


NOW = datetime(2026, 7, 27, 7, tzinfo=timezone.utc)


def _snapshot() -> BraviaCapabilitySnapshot:
    return BraviaCapabilitySnapshot(
        target_alias="living-tv",
        supported_capabilities=frozenset(BraviaCapability),
        observed_at=NOW - timedelta(seconds=10),
        max_age=timedelta(minutes=5),
        volume_range=(0, 60),
        input_aliases=frozenset({"game-console"}),
        channel_aliases=frozenset({"news-channel"}),
        app_aliases=frozenset({"video-app"}),
    )


def _base() -> tuple[str, str, datetime]:
    return "op-1", "living-tv", NOW - timedelta(seconds=1)


@pytest.mark.parametrize(
    "operation_request",
    [
        BraviaPowerRequest(*_base(), BraviaPowerSetting.OFF),
        BraviaVolumeRequest(*_base(), 20),
        BraviaMuteRequest(*_base(), True),
        BraviaInputRequest(*_base(), "game-console"),
        BraviaChannelRequest(*_base(), "news-channel"),
        BraviaAppRequest(*_base(), "video-app"),
        BraviaWakeOnLanRequest(*_base()),
    ],
)
def test_every_declared_bravia_operation_has_typed_dry_run_contract(
    operation_request: object,
) -> None:
    result = BraviaDryRunPlanner(_snapshot()).evaluate(
        operation_request,  # type: ignore[arg-type]
        evaluated_at=NOW,
    )

    assert result.outcome is BraviaDryRunOutcome.WOULD_DISPATCH
    assert result.dispatch_attempted is False


def test_parameters_are_gated_by_observed_capability_details() -> None:
    planner = BraviaDryRunPlanner(_snapshot())

    volume = planner.evaluate(BraviaVolumeRequest(*_base(), 61), evaluated_at=NOW)
    app = planner.evaluate(
        BraviaAppRequest(*_base(), "unobserved-app"),
        evaluated_at=NOW,
    )

    assert volume.outcome is BraviaDryRunOutcome.WOULD_BLOCK
    assert volume.reason_code == "parameter_not_advertised"
    assert app.outcome is BraviaDryRunOutcome.WOULD_BLOCK


def test_missing_parameter_capability_is_indeterminate() -> None:
    snapshot = BraviaCapabilitySnapshot(
        target_alias="living-tv",
        supported_capabilities=frozenset({BraviaCapability.VOLUME}),
        observed_at=NOW,
        max_age=timedelta(minutes=1),
    )

    result = BraviaDryRunPlanner(snapshot).evaluate(
        BraviaVolumeRequest(*_base(), 20),
        evaluated_at=NOW,
    )

    assert result.outcome is BraviaDryRunOutcome.INDETERMINATE
    assert result.reason_code == "parameter_capability_missing"


def test_operation_contract_exposes_no_vendor_wire_details() -> None:
    planner = BraviaDryRunPlanner(_snapshot())

    assert not hasattr(planner, "dispatch")
    assert not hasattr(planner, "execute")
    assert not hasattr(planner, "ircc")
    assert not hasattr(planner, "endpoint")
