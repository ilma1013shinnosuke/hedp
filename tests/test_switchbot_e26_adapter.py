from __future__ import annotations

import json
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hedp.adapters.switchbot.e26.operation import (
    E26OperationAdapter,
    E26State,
    E26CapabilityStatus,
    e26_capabilities,
    parse_e26_status,
)
from hedp.adapters.switchbot.fast_light import (
    FastCommandReceipt,
    FastLightCommand,
    FastLightCommandTransport,
    FastLightTransportError,
)
from hedp.adapters.switchbot.light_control_session import (
    FastLightControlSession,
    PreparedLightOperation,
)
from hedp.adapters.switchbot.operation import (
    LIGHT_EXECUTION_CAPABILITY,
    LightCommand,
    LightDesiredState,
)
from hedp.adapters.switchbot.secondary_state import LightPower, RgbColor
from hedp.operations.execution import Authorization, ExecutionMode, ExecutionOutcome
from hedp.operations.shadow_execution import EvidenceQuality, Intent


NOW = datetime(2026, 7, 27, 6, 0, tzinfo=timezone.utc)
FIXTURE = (
    Path(__file__).parent / "fixtures" / "switchbot" / "e26_adapter_anonymous.json"
)


class Transport(FastLightCommandTransport):
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[FastLightCommand, str]] = []
        self.fail = fail

    def send(
        self, command: FastLightCommand, parameter: str = "default"
    ) -> FastCommandReceipt:
        self.calls.append((command, parameter))
        if self.fail:
            raise FastLightTransportError("sanitized")
        return FastCommandReceipt("e26-smart-bulb", command, True, 2.0)


class Reader:
    def __init__(self, *values: E26State | Exception) -> None:
        self.values = list(values)
        self.calls = 0

    def read_state(self) -> E26State:
        self.calls += 1
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def state(
    *,
    power: LightPower = LightPower.ON,
    brightness: int = 40,
    color: RgbColor = RgbColor(1, 2, 3),
    color_temperature: int = 4200,
    observed_at: datetime = NOW,
    quality: EvidenceQuality = EvidenceQuality.GOOD,
) -> E26State:
    return E26State(power, brightness, color, color_temperature, observed_at, quality)


def intent(desired: LightDesiredState, suffix: str = "1") -> Intent:
    return Intent(
        operation_id=f"e26-formal-{suffix}",
        requested_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
        requester="local-ui",
        reason="explicit local gesture",
        target_alias="e26-smart-bulb",
        capability=LIGHT_EXECUTION_CAPABILITY,
        desired_state=desired,
        priority=1,
        control_owner="hestia",
        correlation_id=f"corr-{suffix}",
    )


def auth(operation: Intent) -> Authorization:
    return Authorization(
        operation.operation_id,
        operation.requester,
        operation.target_alias,
        operation.capability,
        operation.desired_state,
        NOW,
        NOW + timedelta(seconds=30),
    )


def test_fixture_and_capabilities_are_consistent() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    parsed = parse_e26_status(fixture["official_status"], observed_at=NOW)
    statuses = {item.name: item.status for item in e26_capabilities()}

    assert parsed == state(brightness=48, color=RgbColor(12, 34, 56))
    assert all(
        statuses[name] is E26CapabilityStatus.FORMAL
        for name in fixture["capabilities"]["formal"]
    )
    assert all(
        statuses[name] is E26CapabilityStatus.UNSUPPORTED
        for name in fixture["capabilities"]["unsupported"]
    )


def test_execute_has_no_network_preread_and_verifies_after_send() -> None:
    transport = Transport()
    reader = Reader(state(brightness=41, observed_at=NOW + timedelta(milliseconds=1)))
    adapter = E26OperationAdapter(
        transport, reader, clock=lambda: NOW + timedelta(seconds=1)
    )
    operation = intent(LightDesiredState(LightCommand.SET_BRIGHTNESS, 41))

    dispatched = adapter.execute(
        operation,
        evidence=state().evidence(),
        authorization=auth(operation),
        evaluated_at=NOW,
        mode=ExecutionMode.LIVE,
    )

    assert transport.calls == [(FastLightCommand.SET_BRIGHTNESS, "41")]
    assert reader.calls == 0
    assert dispatched.outcome is ExecutionOutcome.PENDING_VERIFICATION
    result = adapter.verify(
        operation,
        precondition=state(),
        dispatched=dispatched,
        evaluated_at=NOW,
    )
    assert reader.calls == 1
    assert result.outcome is ExecutionOutcome.COMPLETED


def test_dry_run_never_sends_or_reads() -> None:
    transport = Transport()
    reader = Reader(state())
    adapter = E26OperationAdapter(transport, reader)
    operation = intent(LightDesiredState(LightCommand.SET_BRIGHTNESS, 41))
    result = adapter.execute(
        operation,
        evidence=state().evidence(),
        authorization=auth(operation),
        evaluated_at=NOW,
        mode=ExecutionMode.SHADOW,
    )
    assert result.outcome is ExecutionOutcome.WOULD_DISPATCH
    assert transport.calls == []
    assert reader.calls == 0


def test_zero_brightness_off_state_and_stale_evidence_are_blocked() -> None:
    transport = Transport()
    reader = Reader(state())
    adapter = E26OperationAdapter(transport, reader)

    zero = intent(LightDesiredState(LightCommand.SET_BRIGHTNESS, 0), "zero")
    assert (
        adapter.execute(
            zero,
            evidence=state().evidence(),
            authorization=auth(zero),
            evaluated_at=NOW,
            mode=ExecutionMode.LIVE,
        ).outcome
        is ExecutionOutcome.BLOCKED
    )

    off = intent(LightDesiredState(LightCommand.SET_BRIGHTNESS, 50), "off")
    assert (
        adapter.execute(
            off,
            evidence=state(power=LightPower.OFF).evidence(),
            authorization=auth(off),
            evaluated_at=NOW,
            mode=ExecutionMode.LIVE,
        ).outcome
        is ExecutionOutcome.BLOCKED
    )

    stale = intent(LightDesiredState(LightCommand.SET_BRIGHTNESS, 50), "stale")
    assert (
        adapter.execute(
            stale,
            evidence=state(observed_at=NOW - timedelta(minutes=1)).evidence(),
            authorization=auth(stale),
            evaluated_at=NOW,
            mode=ExecutionMode.LIVE,
        ).outcome
        is ExecutionOutcome.UNAVAILABLE
    )
    assert transport.calls == []


def test_transport_unknown_is_not_retried_and_latches_stop() -> None:
    transport = Transport(fail=True)
    adapter = E26OperationAdapter(transport, Reader(state()))
    operation = intent(LightDesiredState(LightCommand.SET_BRIGHTNESS, 41))
    result = adapter.execute(
        operation,
        evidence=state().evidence(),
        authorization=auth(operation),
        evaluated_at=NOW,
        mode=ExecutionMode.LIVE,
    )
    assert result.outcome is ExecutionOutcome.UNKNOWN
    assert len(transport.calls) == 1
    assert adapter.safety_stopped


def test_accepted_but_unreadable_is_result_unknown() -> None:
    transport = Transport()
    reader = Reader(RuntimeError("unavailable"))
    adapter = E26OperationAdapter(
        transport, reader, clock=lambda: NOW + timedelta(seconds=1)
    )
    operation = intent(LightDesiredState(LightCommand.SET_BRIGHTNESS, 41))
    result = adapter.execute_and_verify(
        operation,
        evidence=state().evidence(),
        authorization=auth(operation),
        evaluated_at=NOW,
    )
    assert result.outcome is ExecutionOutcome.UNKNOWN
    assert len(transport.calls) == 1
    assert reader.calls == 1
    assert adapter.safety_stopped


def test_constructor_bounds_and_fresh_resynchronization() -> None:
    transport = Transport()
    reader = Reader(state())
    with pytest.raises(ValueError):
        E26OperationAdapter(transport, reader, maximum_state_age=timedelta(0))
    with pytest.raises(ValueError):
        E26OperationAdapter(transport, reader, duplicate_window_seconds=1.01)

    adapter = E26OperationAdapter(Transport(fail=True), reader)
    operation = intent(LightDesiredState(LightCommand.SET_BRIGHTNESS, 41))
    adapter.execute(
        operation,
        evidence=state().evidence(),
        authorization=auth(operation),
        evaluated_at=NOW,
        mode=ExecutionMode.LIVE,
    )
    assert adapter.safety_stopped
    adapter.resume_after_resynchronization(state(), evaluated_at=NOW)
    assert not adapter.safety_stopped


def test_e26_slider_latest_wins_without_readback_blocking_dispatch() -> None:
    transport = Transport()
    reader = Reader(state())
    adapter = E26OperationAdapter(transport, reader)
    results: list[ExecutionOutcome] = []
    session = FastLightControlSession(
        adapter,
        debounce_seconds=0.02,
        result_callback=lambda result: results.append(result.outcome),
    )

    def prepared(index: int, brightness: int) -> PreparedLightOperation:
        operation = intent(
            LightDesiredState(LightCommand.SET_BRIGHTNESS, brightness),
            f"slider-{index}",
        )
        return PreparedLightOperation(
            operation, state().evidence(), auth(operation), NOW
        )

    try:
        session.submit_latest(prepared(1, 20))
        session.submit_latest(prepared(2, 40))
        session.submit_latest(prepared(3, 60))
        assert session.wait_idle()
    finally:
        session.close()

    assert transport.calls == [(FastLightCommand.SET_BRIGHTNESS, "60")]
    assert reader.calls == 0
    assert results == [ExecutionOutcome.PENDING_VERIFICATION]
