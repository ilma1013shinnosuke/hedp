from datetime import datetime, timedelta, timezone

import pytest

from hedp.observations import Quality
from hedp.adapters.fusionsolar.operation import (
    DispatchStatus,
    FusionSolarCommand,
    FusionSolarOperationAdapter,
    FusionSolarOperationRequest,
    FusionSolarOperationTimeout,
    FusionSolarVendorReceipt,
    OperationOutcome,
    RuntimeCapabilitySnapshot,
    VerificationStatus,
)
from hedp.adapters.fusionsolar.state import (
    BatteryMode,
    FusionSolarControlState,
    GenerationStatus,
    normalize_battery_mode,
)


NOW = datetime(2026, 7, 27, 0, 0, tzinfo=timezone.utc)
COMMANDS = frozenset(FusionSolarCommand)


class FakeTransport:
    is_fixture = True

    def __init__(self, response=None):
        self.response = response or FusionSolarVendorReceipt(DispatchStatus.ACCEPTED)
        self.calls = []

    def dispatch(self, request):
        self.calls.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FakeReader:
    def __init__(self, state):
        self.state = state
        self.calls = []

    def read_state(self, target_alias):
        self.calls.append(target_alias)
        return self.state


def snapshot(commands=COMMANDS):
    return RuntimeCapabilitySnapshot(
        "home_solar",
        commands,
        NOW,
        timedelta(minutes=5),
    )


def request(command, *, dry_run=True):
    return FusionSolarOperationRequest(
        f"op-{command.value.replace('_', '-')}",
        "home_solar",
        command,
        NOW,
        dry_run,
    )


def test_battery_mode_normalization_is_typed_and_does_not_infer_unknowns():
    assert normalize_battery_mode(" Charging ") is BatteryMode.CHARGING
    assert normalize_battery_mode("discharge") is BatteryMode.DISCHARGING
    assert normalize_battery_mode("standby") is BatteryMode.STANDBY
    assert normalize_battery_mode(-1200) is BatteryMode.UNKNOWN
    assert normalize_battery_mode("vendor mode 7") is BatteryMode.UNKNOWN

    state = FusionSolarControlState.from_values(
        generation_status="stopped",
        battery_mode="vendor mode 7",
        observed_at=NOW,
    )
    assert state.generation_status is GenerationStatus.STOPPED
    assert state.battery_mode is BatteryMode.UNKNOWN
    assert "vendor mode 7" not in repr(state)


@pytest.mark.parametrize("command", list(FusionSolarCommand))
def test_all_requested_commands_are_capability_gated_dry_runs(command):
    transport = FakeTransport()
    reader = FakeReader(
        FusionSolarControlState(GenerationStatus.UNKNOWN, BatteryMode.UNKNOWN, NOW)
    )
    result = FusionSolarOperationAdapter(
        snapshot(), transport=transport, state_reader=reader, clock=lambda: NOW
    ).execute(request(command))

    assert result.dispatch.status is DispatchStatus.DRY_RUN
    assert result.dispatch.attempt_number == 0
    assert result.verification.status is VerificationStatus.NOT_ATTEMPTED
    assert result.outcome is OperationOutcome.PLANNED
    assert transport.calls == []
    assert reader.calls == []


def test_absent_or_stale_capability_blocks_before_dispatch():
    transport = FakeTransport()
    adapter = FusionSolarOperationAdapter(
        snapshot(frozenset({FusionSolarCommand.CHARGE})),
        transport=transport,
        clock=lambda: NOW,
    )
    with pytest.raises(PermissionError, match="absent"):
        adapter.execute(request(FusionSolarCommand.DISCHARGE, dry_run=False))

    stale = RuntimeCapabilitySnapshot(
        "home_solar",
        COMMANDS,
        NOW - timedelta(hours=1),
        timedelta(minutes=5),
    )
    with pytest.raises(PermissionError, match="stale"):
        FusionSolarOperationAdapter(
            stale, transport=transport, clock=lambda: NOW
        ).execute(request(FusionSolarCommand.CHARGE, dry_run=False))
    assert transport.calls == []


def test_qualified_dispatch_occurs_once_then_reads_back_once():
    transport = FakeTransport()
    reader = FakeReader(
        FusionSolarControlState(
            GenerationStatus.GENERATING, BatteryMode.DISCHARGING, NOW
        )
    )
    result = FusionSolarOperationAdapter(
        snapshot(), transport=transport, state_reader=reader, clock=lambda: NOW
    ).execute(request(FusionSolarCommand.DISCHARGE, dry_run=False))

    assert len(transport.calls) == 1
    assert reader.calls == ["home_solar"]
    assert result.dispatch.attempt_number == 1
    assert result.verification.status is VerificationStatus.MATCHED
    assert result.outcome is OperationOutcome.COMPLETED


def test_timeout_is_unknown_without_redispatch_or_readback():
    transport = FakeTransport(FusionSolarOperationTimeout())
    reader = FakeReader(
        FusionSolarControlState(GenerationStatus.STOPPED, BatteryMode.UNKNOWN, NOW)
    )
    result = FusionSolarOperationAdapter(
        snapshot(), transport=transport, state_reader=reader, clock=lambda: NOW
    ).execute(request(FusionSolarCommand.STOP_GENERATION, dry_run=False))

    assert len(transport.calls) == 1
    assert reader.calls == []
    assert result.dispatch.status is DispatchStatus.TIMEOUT
    assert result.outcome is OperationOutcome.UNKNOWN


def test_non_dry_run_has_no_implicit_live_transport():
    with pytest.raises(PermissionError, match="dry-run or fixture-only"):
        FusionSolarOperationAdapter(snapshot(), clock=lambda: NOW).execute(
            request(FusionSolarCommand.CHARGE, dry_run=False)
        )


def test_unmarked_transport_is_rejected_as_potential_live_send():
    class UnmarkedTransport:
        def dispatch(self, request):
            raise AssertionError("must not dispatch")

    with pytest.raises(ValueError, match="fixture-only"):
        FusionSolarOperationAdapter(snapshot(), transport=UnmarkedTransport())


@pytest.mark.parametrize(
    ("state", "command"),
    [
        (
            FusionSolarControlState(
                GenerationStatus.STOPPED,
                BatteryMode.IDLE,
                NOW - timedelta(seconds=1),
            ),
            FusionSolarCommand.STOP_GENERATION,
        ),
        (
            FusionSolarControlState(
                GenerationStatus.GENERATING,
                BatteryMode.CHARGING,
                NOW,
                battery_quality=Quality.UNKNOWN,
            ),
            FusionSolarCommand.CHARGE,
        ),
    ],
)
def test_stale_or_insufficient_quality_readback_cannot_complete(state, command):
    result = FusionSolarOperationAdapter(
        snapshot(),
        transport=FakeTransport(),
        state_reader=FakeReader(state),
        clock=lambda: NOW,
    ).execute(request(command, dry_run=False))

    assert result.verification.status is VerificationStatus.UNAVAILABLE
    assert result.outcome is OperationOutcome.UNKNOWN
