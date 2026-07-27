from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

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
from hedp.adapters.switchbot.strip_light.operation import (
    StripLight3OpenApiReader,
    StripLight3OperationAdapter,
    StripLight3State,
    StripLightCapabilityStatus,
    StripLightReadError,
    parse_strip_light_3_status,
    strip_light_3_capabilities,
)
from hedp.operations.execution import (
    Authorization,
    ExecutionMode,
    ExecutionOutcome,
)
from hedp.operations.shadow_execution import EvidenceQuality, Intent


NOW = datetime(2026, 7, 27, 6, 0, tzinfo=timezone.utc)
FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "switchbot"
    / "strip_light_3_adapter_anonymous.json"
)


class RecordingTransport(FastLightCommandTransport):
    def __init__(
        self,
        *,
        accepted: bool = True,
        failure: str | None = None,
    ) -> None:
        self.calls: list[tuple[FastLightCommand, str]] = []
        self.accepted = accepted
        self.failure = failure

    def send(
        self,
        command: FastLightCommand,
        parameter: str = "default",
    ) -> FastCommandReceipt:
        self.calls.append((command, parameter))
        if self.failure is not None:
            raise FastLightTransportError(self.failure)
        return FastCommandReceipt(
            "strip-light-3",
            command,
            self.accepted,
            3.0,
        )


class StateReader:
    def __init__(self, *states: StripLight3State | Exception) -> None:
        self.states = list(states)
        self.calls = 0

    def read_state(self) -> StripLight3State:
        self.calls += 1
        value = self.states.pop(0)
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
) -> StripLight3State:
    return StripLight3State(
        power,
        brightness,
        color,
        color_temperature,
        observed_at,
        quality,
    )


def intent(
    desired: LightDesiredState,
    *,
    operation_id: str = "strip-formal-1",
) -> Intent:
    return Intent(
        operation_id=operation_id,
        requested_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
        requester="local-ui",
        reason="explicit local gesture",
        target_alias="strip-light-3",
        capability=LIGHT_EXECUTION_CAPABILITY,
        desired_state=desired,
        priority=1,
        control_owner="hestia",
        correlation_id=f"corr-{operation_id}",
    )


def authorization(operation: Intent) -> Authorization:
    return Authorization(
        operation_id=operation.operation_id,
        requester=operation.requester,
        target_alias=operation.target_alias,
        capability=operation.capability,
        desired_state=operation.desired_state,
        granted_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
    )


def formal_adapter(
    transport: RecordingTransport,
    reader: StateReader,
    **kwargs: object,
) -> StripLight3OperationAdapter:
    return StripLight3OperationAdapter(
        transport,
        reader,
        clock=lambda: NOW + timedelta(seconds=1),
        **kwargs,
    )


def execute(
    adapter: StripLight3OperationAdapter,
    operation: Intent,
    before: StripLight3State,
    *,
    mode: ExecutionMode = ExecutionMode.LIVE,
):
    if mode is ExecutionMode.LIVE:
        return adapter.execute_and_verify(
            operation,
            evidence=before.evidence(),
            authorization=authorization(operation),
            evaluated_at=NOW,
        )
    return adapter.execute(
        operation,
        evidence=before.evidence(),
        authorization=authorization(operation),
        evaluated_at=NOW,
        mode=mode,
    )


def test_anonymous_fixture_parser_and_capability_table_are_consistent() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    parsed = parse_strip_light_3_status(
        fixture["official_status"],
        observed_at=NOW,
    )
    statuses = {
        item.name: item.status for item in strip_light_3_capabilities()
    }

    assert parsed == state(
        brightness=48,
        color=RgbColor(12, 34, 56),
    )
    for name in fixture["capabilities"]["formal"]:
        assert statuses[name] is StripLightCapabilityStatus.FORMAL
    for name in fixture["capabilities"]["unsupported"]:
        assert statuses[name] is StripLightCapabilityStatus.UNSUPPORTED


@pytest.mark.parametrize(
    ("desired", "after", "expected_command"),
    [
        (
            LightDesiredState(LightCommand.SET_POWER, LightPower.OFF),
            state(power=LightPower.OFF, observed_at=NOW + timedelta(milliseconds=1)),
            (FastLightCommand.TURN_OFF, "default"),
        ),
        (
            LightDesiredState(LightCommand.SET_BRIGHTNESS, 41),
            state(brightness=41, observed_at=NOW + timedelta(milliseconds=1)),
            (FastLightCommand.SET_BRIGHTNESS, "41"),
        ),
        (
            LightDesiredState(LightCommand.SET_COLOR, RgbColor(7, 8, 9)),
            state(
                color=RgbColor(7, 8, 9),
                observed_at=NOW + timedelta(milliseconds=1),
            ),
            (FastLightCommand.SET_COLOR, "7:8:9"),
        ),
        (
            LightDesiredState(LightCommand.SET_COLOR_TEMPERATURE, 4300),
            state(
                color_temperature=4300,
                observed_at=NOW + timedelta(milliseconds=1),
            ),
            (FastLightCommand.SET_COLOR_TEMPERATURE, "4300"),
        ),
    ],
)
def test_formal_operations_gate_send_once_and_complete_after_one_readback(
    desired: LightDesiredState,
    after: StripLight3State,
    expected_command: tuple[FastLightCommand, str],
) -> None:
    transport = RecordingTransport()
    reader = StateReader(after)
    adapter = formal_adapter(transport, reader)

    result = execute(adapter, intent(desired), state())

    assert transport.calls == [expected_command]
    assert reader.calls == 1
    assert result.outcome is ExecutionOutcome.COMPLETED
    assert result.adapter_result is not None
    assert result.adapter_result.dispatch_status == "accepted"
    assert result.adapter_result.verification_status == "matched"


def test_dry_run_stops_before_command_and_readback() -> None:
    transport = RecordingTransport()
    reader = StateReader(state())
    adapter = formal_adapter(transport, reader)
    operation = intent(
        LightDesiredState(LightCommand.SET_BRIGHTNESS, 41),
    )

    result = execute(adapter, operation, state(), mode=ExecutionMode.SHADOW)

    assert result.outcome is ExecutionOutcome.WOULD_DISPATCH
    assert result.dispatch_attempted is False
    assert transport.calls == []
    assert reader.calls == 0


@pytest.mark.parametrize(
    "brightness",
    [0],
)
def test_formal_brightness_boundaries_fail_closed(
    brightness: int,
) -> None:
    transport = RecordingTransport()
    reader = StateReader(state())
    adapter = formal_adapter(transport, reader)
    operation = intent(
        LightDesiredState(LightCommand.SET_BRIGHTNESS, brightness),
    )

    result = execute(adapter, operation, state())

    assert result.gate.reason_code == "desired_state_invalid"
    assert result.dispatch_attempted is False
    assert transport.calls == []
    assert reader.calls == 0


def test_brightness_while_power_off_is_blocked_without_implicit_power_on() -> None:
    transport = RecordingTransport()
    reader = StateReader(state())
    adapter = formal_adapter(transport, reader)
    operation = intent(
        LightDesiredState(LightCommand.SET_BRIGHTNESS, 41),
    )

    result = execute(
        adapter,
        operation,
        state(power=LightPower.OFF),
    )

    assert result.gate.reason_code == "power_off_requires_explicit_power_on"
    assert transport.calls == []
    assert reader.calls == 0


def test_stale_state_is_rejected_by_execution_gate() -> None:
    transport = RecordingTransport()
    reader = StateReader(state())
    adapter = formal_adapter(transport, reader)
    before = state(
        observed_at=NOW - timedelta(minutes=1),
        quality=EvidenceQuality.STALE,
    )
    operation = intent(
        LightDesiredState(LightCommand.SET_BRIGHTNESS, 41),
    )

    result = execute(adapter, operation, before)

    assert result.gate.reason_code == "state_quality_insufficient"
    assert transport.calls == []
    assert reader.calls == 0


def test_timeout_is_result_unknown_not_retried_and_latches_safe_stop() -> None:
    transport = RecordingTransport(failure="timeout")
    reader = StateReader(state())
    adapter = formal_adapter(transport, reader)
    operation = intent(
        LightDesiredState(LightCommand.SET_BRIGHTNESS, 41),
    )

    result = execute(adapter, operation, state())
    next_result = execute(
        adapter,
        intent(
            LightDesiredState(LightCommand.SET_BRIGHTNESS, 42),
            operation_id="strip-formal-2",
        ),
        state(),
    )

    assert result.outcome is ExecutionOutcome.UNKNOWN
    assert transport.calls == [(FastLightCommand.SET_BRIGHTNESS, "41")]
    assert reader.calls == 0
    assert adapter.safety_stopped is True
    assert next_result.gate.reason_code == "adapter_safety_stopped"


def test_safety_stop_cannot_be_bypassed_by_a_semantic_noop() -> None:
    transport = RecordingTransport(failure="timeout")
    reader = StateReader(state())
    adapter = formal_adapter(transport, reader)
    first = intent(
        LightDesiredState(LightCommand.SET_BRIGHTNESS, 41),
    )
    execute(adapter, first, state())

    stopped = execute(
        adapter,
        intent(
            LightDesiredState(LightCommand.SET_BRIGHTNESS, 40),
            operation_id="strip-formal-2",
        ),
        state(brightness=40),
    )

    assert stopped.gate.reason_code == "adapter_safety_stopped"
    assert stopped.dispatch_attempted is False
    assert len(transport.calls) == 1


def test_only_fresh_good_resynchronization_can_clear_safety_stop() -> None:
    transport = RecordingTransport(failure="timeout")
    reader = StateReader(state())
    adapter = formal_adapter(transport, reader)
    execute(
        adapter,
        intent(LightDesiredState(LightCommand.SET_BRIGHTNESS, 41)),
        state(),
    )

    with pytest.raises(PermissionError):
        adapter.resume_after_resynchronization(
            state(
                observed_at=NOW - timedelta(minutes=1),
                quality=EvidenceQuality.STALE,
            ),
            evaluated_at=NOW,
        )
    adapter.resume_after_resynchronization(state(), evaluated_at=NOW)

    assert adapter.safety_stopped is False


def test_readback_failure_is_unknown_and_no_command_is_retried() -> None:
    transport = RecordingTransport()
    reader = StateReader(StripLightReadError("connection_failed"))
    adapter = formal_adapter(transport, reader)

    result = execute(
        adapter,
        intent(LightDesiredState(LightCommand.SET_BRIGHTNESS, 41)),
        state(),
    )

    assert result.outcome is ExecutionOutcome.UNKNOWN
    assert transport.calls == [(FastLightCommand.SET_BRIGHTNESS, "41")]
    assert reader.calls == 1
    assert adapter.safety_stopped is True


def test_semantic_noop_and_rapid_duplicate_are_suppressed() -> None:
    transport = RecordingTransport()
    times = iter((10.0, 10.1))
    reader = StateReader(
        state(brightness=41, observed_at=NOW + timedelta(milliseconds=1)),
    )
    adapter = formal_adapter(
        transport,
        reader,
        monotonic=lambda: next(times),
    )
    already = execute(
        adapter,
        intent(LightDesiredState(LightCommand.SET_BRIGHTNESS, 40)),
        state(brightness=40),
    )
    first = execute(
        adapter,
        intent(
            LightDesiredState(LightCommand.SET_BRIGHTNESS, 41),
            operation_id="strip-formal-2",
        ),
        state(),
    )
    duplicate = execute(
        adapter,
        intent(
            LightDesiredState(LightCommand.SET_BRIGHTNESS, 41),
            operation_id="strip-formal-3",
        ),
        state(),
    )

    assert already.outcome is ExecutionOutcome.COMPLETED
    assert already.dispatch_attempted is False
    assert first.outcome is ExecutionOutcome.COMPLETED
    assert duplicate.gate.reason_code == "duplicate_desired_state"
    assert transport.calls == [(FastLightCommand.SET_BRIGHTNESS, "41")]


def test_same_stored_color_cannot_claim_active_mode_confirmation() -> None:
    transport = RecordingTransport()
    before = state(color=RgbColor(1, 2, 3))
    reader = StateReader(
        state(
            color=RgbColor(1, 2, 3),
            observed_at=NOW + timedelta(milliseconds=1),
        )
    )
    adapter = formal_adapter(transport, reader)

    result = execute(
        adapter,
        intent(
            LightDesiredState(
                LightCommand.SET_COLOR,
                RgbColor(1, 2, 3),
            )
        ),
        before,
    )

    assert result.outcome is ExecutionOutcome.UNKNOWN
    assert result.audit_events[-1].reason_code == "active_mode_not_observable"
    assert transport.calls == [(FastLightCommand.SET_COLOR, "1:2:3")]


def test_existing_fast_slider_session_uses_formal_adapter_and_latest_value() -> None:
    transport = RecordingTransport()
    reader = StateReader(
        state(brightness=60, observed_at=NOW + timedelta(milliseconds=1)),
    )
    adapter = formal_adapter(transport, reader)
    outcomes: list[ExecutionOutcome] = []
    session = FastLightControlSession(
        adapter,
        debounce_seconds=0.02,
        result_callback=lambda result: outcomes.append(result.outcome),
    )
    try:
        for index, brightness in enumerate((20, 40, 60), start=1):
            operation = intent(
                LightDesiredState(LightCommand.SET_BRIGHTNESS, brightness),
                operation_id=f"strip-slider-formal-{index}",
            )
            session.submit_latest(
                PreparedLightOperation(
                    operation,
                    state().evidence(),
                    authorization(operation),
                    NOW,
                )
            )
        assert session.wait_idle()
    finally:
        session.close()

    assert transport.calls == [(FastLightCommand.SET_BRIGHTNESS, "60")]
    assert reader.calls == 0
    assert outcomes == [ExecutionOutcome.PENDING_VERIFICATION]


def test_fast_execute_latency_measurement_excludes_readback() -> None:
    transport = RecordingTransport()
    reader = StateReader(
        state(brightness=41, observed_at=NOW + timedelta(milliseconds=1)),
    )
    latency_times = iter((100.0, 100.012))
    adapter = formal_adapter(
        transport,
        reader,
        latency_monotonic=lambda: next(latency_times),
    )
    operation = intent(
        LightDesiredState(LightCommand.SET_BRIGHTNESS, 41),
    )

    dispatched = adapter.execute(
        operation,
        evidence=state().evidence(),
        authorization=authorization(operation),
        evaluated_at=NOW,
        mode=ExecutionMode.LIVE,
    )

    assert dispatched.outcome is ExecutionOutcome.PENDING_VERIFICATION
    assert adapter.last_fast_execute_ms == pytest.approx(12)
    assert reader.calls == 0
    assert transport.calls == [(FastLightCommand.SET_BRIGHTNESS, "41")]


def test_verification_intent_must_match_the_dispatched_operation() -> None:
    transport = RecordingTransport()
    reader = StateReader(
        state(brightness=41, observed_at=NOW + timedelta(milliseconds=1)),
    )
    adapter = formal_adapter(transport, reader)
    dispatched_intent = intent(
        LightDesiredState(LightCommand.SET_BRIGHTNESS, 41),
    )
    dispatched = adapter.execute(
        dispatched_intent,
        evidence=state().evidence(),
        authorization=authorization(dispatched_intent),
        evaluated_at=NOW,
        mode=ExecutionMode.LIVE,
    )
    other_intent = intent(
        LightDesiredState(LightCommand.SET_BRIGHTNESS, 42),
        operation_id="strip-formal-2",
    )

    with pytest.raises(ValueError, match="does not match"):
        adapter.verify(
            other_intent,
            precondition=state(),
            dispatched=dispatched,
            evaluated_at=NOW,
        )

    assert reader.calls == 0


class HttpResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int = 4096):
        yield json.dumps(self.payload).encode()


def test_openapi_reader_performs_one_get_and_hides_private_values() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    calls: list[tuple[str, dict[str, object]]] = []

    def get(url: str, **kwargs: object) -> HttpResponse:
        calls.append((url, kwargs))
        return HttpResponse(fixture["official_status"])

    reader = StripLight3OpenApiReader(
        "private-token",
        "private-secret",
        "private-device-id",
        request_get=get,
        clock=lambda: NOW,
    )

    observed = reader.read_state()

    assert observed.brightness == 48
    assert len(calls) == 1
    assert calls[0][1]["timeout"] == 3.0
    rendered = json.dumps(observed.safe_summary())
    assert "private" not in rendered


def test_openapi_reader_timeout_is_sanitized_and_not_retried() -> None:
    calls = 0

    def get(*args: object, **kwargs: object) -> HttpResponse:
        nonlocal calls
        calls += 1
        raise requests.Timeout("private URL and device")

    reader = StripLight3OpenApiReader(
        "private-token",
        "private-secret",
        "private-device-id",
        request_get=get,
    )

    with pytest.raises(StripLightReadError) as captured:
        reader.read_state()

    assert calls == 1
    assert captured.value.reason_code == "timeout"
    assert "private" not in str(captured.value)
