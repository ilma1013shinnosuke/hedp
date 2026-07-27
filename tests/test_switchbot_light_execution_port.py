from datetime import datetime, timedelta, timezone

import pytest

from hedp.adapters.switchbot.fast_light import (
    FastCommandReceipt,
    FastLightCommand,
    FastLightCommandTransport,
    FastLightTransportError,
)
from hedp.adapters.switchbot.operation import (
    FastLightExecutionPort,
    LIGHT_EXECUTION_CAPABILITY,
    LightCapabilitySnapshot,
    LightCommand,
    LightDesiredState,
)
from hedp.adapters.switchbot.secondary_state import (
    LightPower,
    RgbColor,
    SecondaryDeviceKind,
)
from hedp.operations.execution import (
    Authorization,
    ExecutionCoordinator,
    ExecutionMode,
    ExecutionOutcome,
)
from hedp.operations.shadow_execution import EvidenceQuality, Intent, StateEvidence


NOW = datetime(2026, 7, 27, 1, 0, tzinfo=timezone.utc)


class FakeFastTransport(FastLightCommandTransport):
    def __init__(self, *, accepted: bool = True) -> None:
        self.calls: list[tuple[FastLightCommand, str]] = []
        self.accepted = accepted

    def send(
        self,
        command: FastLightCommand,
        parameter: str = "default",
    ) -> FastCommandReceipt:
        self.calls.append((command, parameter))
        return FastCommandReceipt(
            "strip-light-3",
            command,
            self.accepted,
            12.0,
        )


def _snapshot() -> LightCapabilitySnapshot:
    return LightCapabilitySnapshot(
        "strip-light-3",
        SecondaryDeviceKind.STRIP_LIGHT_3,
        frozenset(LightCommand),
        NOW,
        timedelta(minutes=5),
    )


def _intent(desired: LightDesiredState) -> Intent:
    return Intent(
        operation_id="strip-operation-1",
        requested_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
        requester="local-ui",
        reason="user gesture",
        target_alias="strip-light-3",
        capability=LIGHT_EXECUTION_CAPABILITY,
        desired_state=desired,
        priority=1,
        control_owner="hestia",
        correlation_id="gesture-1",
    )


def _authorization(intent: Intent) -> Authorization:
    return Authorization(
        operation_id=intent.operation_id,
        requester=intent.requester,
        target_alias=intent.target_alias,
        capability=intent.capability,
        desired_state=intent.desired_state,
        granted_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(seconds=30),
    )


def _evidence() -> StateEvidence:
    return StateEvidence(
        target_alias="strip-light-3",
        capability=LIGHT_EXECUTION_CAPABILITY,
        observed_at=NOW,
        quality=EvidenceQuality.GOOD,
        current_state=LightPower.ON,
    )


@pytest.mark.parametrize(
    ("desired", "expected"),
    [
        (
            LightDesiredState(LightCommand.SET_POWER, LightPower.ON),
            (FastLightCommand.TURN_ON, "default"),
        ),
        (
            LightDesiredState(LightCommand.SET_BRIGHTNESS, 55),
            (FastLightCommand.SET_BRIGHTNESS, "55"),
        ),
        (
            LightDesiredState(LightCommand.SET_COLOR_TEMPERATURE, 4200),
            (FastLightCommand.SET_COLOR_TEMPERATURE, "4200"),
        ),
        (
            LightDesiredState(LightCommand.SET_COLOR, RgbColor(1, 2, 3)),
            (FastLightCommand.SET_COLOR, "1:2:3"),
        ),
    ],
)
def test_live_execution_gate_dispatches_one_cached_transport_call(
    desired: LightDesiredState,
    expected: tuple[FastLightCommand, str],
) -> None:
    transport = FakeFastTransport()
    port = FastLightExecutionPort(transport, target_alias="strip-light-3")
    intent = _intent(desired)
    coordinator = ExecutionCoordinator(
        (_snapshot().execution_capability(control_owner="hestia"),),
        {(intent.target_alias, intent.capability): port},
    )

    result = coordinator.execute(
        intent,
        evidence=_evidence(),
        authorization=_authorization(intent),
        evaluated_at=NOW,
        mode=ExecutionMode.LIVE,
    )

    assert transport.calls == [expected]
    assert result.dispatch_attempted is True
    assert result.adapter_result is not None
    assert result.adapter_result.dispatch_status == "accepted"
    assert result.adapter_result.verification_status == "pending"
    assert result.outcome is ExecutionOutcome.PENDING_VERIFICATION


def test_live_mode_rejects_fixture_port_before_dispatch() -> None:
    class FixturePort:
        fixture_only = True
        production_execution_enabled = False

        def execute(self, _intent: Intent):
            raise AssertionError("fixture must not run in live mode")

    desired = LightDesiredState(LightCommand.SET_BRIGHTNESS, 50)
    intent = _intent(desired)
    coordinator = ExecutionCoordinator(
        (_snapshot().execution_capability(control_owner="hestia"),),
        {(intent.target_alias, intent.capability): FixturePort()},
    )

    result = coordinator.execute(
        intent,
        evidence=_evidence(),
        authorization=_authorization(intent),
        evaluated_at=NOW,
        mode=ExecutionMode.LIVE,
    )

    assert result.gate.reason_code == "production_port_required"
    assert result.dispatch_attempted is False


def test_sanitized_transport_failure_is_unknown_and_not_retried() -> None:
    class FailingFastTransport(FakeFastTransport):
        def send(
            self,
            command: FastLightCommand,
            parameter: str = "default",
        ) -> FastCommandReceipt:
            self.calls.append((command, parameter))
            raise FastLightTransportError("connection_failed")

    transport = FailingFastTransport()
    port = FastLightExecutionPort(transport, target_alias="strip-light-3")
    desired = LightDesiredState(LightCommand.SET_BRIGHTNESS, 55)
    intent = _intent(desired)
    coordinator = ExecutionCoordinator(
        (_snapshot().execution_capability(control_owner="hestia"),),
        {(intent.target_alias, intent.capability): port},
    )

    result = coordinator.execute(
        intent,
        evidence=_evidence(),
        authorization=_authorization(intent),
        evaluated_at=NOW,
        mode=ExecutionMode.LIVE,
    )

    assert transport.calls == [(FastLightCommand.SET_BRIGHTNESS, "55")]
    assert result.outcome is ExecutionOutcome.UNKNOWN
    assert result.adapter_result is not None
    assert result.adapter_result.dispatch_status == "transport_error"
    assert result.adapter_result.verification_status == "unavailable"


@pytest.mark.parametrize(
    "value",
    [2699, 6501, True],
)
def test_color_temperature_validation_fails_before_transport(value: object) -> None:
    with pytest.raises(ValueError, match="2700 to 6500"):
        LightDesiredState(LightCommand.SET_COLOR_TEMPERATURE, value)


def test_model_specific_brightness_minimum_is_enforced_by_the_gate() -> None:
    e26_snapshot = LightCapabilitySnapshot(
        "e26-smart-bulb",
        SecondaryDeviceKind.E26_SMART_BULB,
        frozenset(LightCommand),
        NOW,
        timedelta(minutes=5),
    )
    strip_snapshot = _snapshot()
    e26_validator = e26_snapshot.execution_capability(
        control_owner="hestia"
    ).desired_state_validator
    strip_validator = strip_snapshot.execution_capability(
        control_owner="hestia"
    ).desired_state_validator

    assert e26_validator is not None
    assert strip_validator is not None
    assert e26_validator(LightDesiredState(LightCommand.SET_BRIGHTNESS, 0)) is False
    assert strip_validator(LightDesiredState(LightCommand.SET_BRIGHTNESS, 0)) is True
