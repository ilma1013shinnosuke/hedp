from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hedp.adapters.switchbot.fast_light import (
    FastCommandReceipt,
    FastLightCommand,
    FastLightCommandTransport,
)
from hedp.adapters.switchbot.light_control_session import (
    FastLightControlSession,
    PreparedLightOperation,
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
    SecondaryDeviceKind,
)
from hedp.operations.execution import (
    Authorization,
    ExecutionCoordinator,
    ExecutionOutcome,
)
from hedp.operations.shadow_execution import EvidenceQuality, Intent, StateEvidence


NOW = datetime(2026, 7, 27, 1, 0, tzinfo=timezone.utc)


class RecordingTransport(FastLightCommandTransport):
    def __init__(self) -> None:
        self.calls: list[tuple[FastLightCommand, str]] = []

    def send(
        self,
        command: FastLightCommand,
        parameter: str = "default",
    ) -> FastCommandReceipt:
        self.calls.append((command, parameter))
        return FastCommandReceipt(
            "strip-light-3",
            command,
            True,
            5.0,
        )


def _session(
    transport: RecordingTransport,
    results: list[ExecutionOutcome],
    *,
    debounce_seconds: float = 0.02,
) -> FastLightControlSession:
    snapshot = LightCapabilitySnapshot(
        "strip-light-3",
        SecondaryDeviceKind.STRIP_LIGHT_3,
        frozenset(LightCommand),
        NOW,
        timedelta(minutes=5),
    )
    port = FastLightExecutionPort(transport, target_alias="strip-light-3")
    coordinator = ExecutionCoordinator(
        (snapshot.execution_capability(control_owner="hestia"),),
        {("strip-light-3", LIGHT_EXECUTION_CAPABILITY): port},
    )
    return FastLightControlSession(
        coordinator,
        debounce_seconds=debounce_seconds,
        result_callback=lambda result: results.append(result.outcome),
    )


def _operation(index: int, brightness: int) -> PreparedLightOperation:
    operation_id = f"strip-slider-{index}"
    desired = LightDesiredState(LightCommand.SET_BRIGHTNESS, brightness)
    intent = Intent(
        operation_id=operation_id,
        requested_at=NOW,
        expires_at=NOW + timedelta(minutes=1),
        requester="local-ui",
        reason="slider gesture",
        target_alias="strip-light-3",
        capability=LIGHT_EXECUTION_CAPABILITY,
        desired_state=desired,
        priority=1,
        control_owner="hestia",
        correlation_id=f"slider-gesture-{index}",
    )
    authorization = Authorization(
        operation_id=operation_id,
        requester="local-ui",
        target_alias="strip-light-3",
        capability=LIGHT_EXECUTION_CAPABILITY,
        desired_state=desired,
        granted_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=1),
    )
    evidence = StateEvidence(
        target_alias="strip-light-3",
        capability=LIGHT_EXECUTION_CAPABILITY,
        observed_at=NOW,
        quality=EvidenceQuality.GOOD,
        current_state=LightPower.ON,
    )
    return PreparedLightOperation(intent, evidence, authorization, NOW)


def test_rapid_slider_updates_send_only_the_latest_unsent_value() -> None:
    transport = RecordingTransport()
    results: list[ExecutionOutcome] = []
    session = _session(transport, results)
    try:
        session.submit_latest(_operation(1, 20))
        session.submit_latest(_operation(2, 40))
        session.submit_latest(_operation(3, 60))

        assert session.wait_idle()
    finally:
        session.close()

    assert transport.calls == [(FastLightCommand.SET_BRIGHTNESS, "60")]
    assert results == [ExecutionOutcome.PENDING_VERIFICATION]


def test_button_command_dispatches_immediately_through_execution_gate() -> None:
    transport = RecordingTransport()
    results: list[ExecutionOutcome] = []
    session = _session(transport, results)
    try:
        result = session.send_immediately(_operation(1, 72))
    finally:
        session.close()

    assert transport.calls == [(FastLightCommand.SET_BRIGHTNESS, "72")]
    assert result.outcome is ExecutionOutcome.PENDING_VERIFICATION
    assert results == [ExecutionOutcome.PENDING_VERIFICATION]


def test_close_discards_pending_slider_value() -> None:
    transport = RecordingTransport()
    session = _session(transport, [], debounce_seconds=0.2)

    session.submit_latest(_operation(1, 20))
    session.close(discard_pending=True)

    assert transport.calls == []
