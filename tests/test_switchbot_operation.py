from datetime import datetime, timedelta, timezone

import pytest

from hedp.observations import Quality
from hedp.adapters.switchbot.operation import (
    DispatchStatus,
    OperationOutcome,
    RobotCommand,
    RobotOperationAdapter,
    RobotOperationRequest,
    RobotVendorReceipt,
    RuntimeCapabilitySnapshot,
    S10CleanParameters,
    SwitchBotOperationTimeout,
    VerificationStatus,
    official_commands_for,
)
from hedp.adapters.switchbot.robot_state import (
    RobotChargingStatus,
    RobotState,
    RobotTaskStatus,
    RobotWorkingStatus,
    normalize_robot_state,
)
from hedp.adapters.switchbot.support import (
    FeatureDisposition,
    SwitchBotFeature,
    feature_support,
)


NOW = datetime(2026, 7, 27, 0, 0, tzinfo=timezone.utc)
K10_COMMANDS = frozenset({RobotCommand.START, RobotCommand.STOP, RobotCommand.DOCK})


class FakeTransport:
    def __init__(self, response=None):
        self.response = response or RobotVendorReceipt(DispatchStatus.ACCEPTED)
        self.calls = []

    def dispatch(self, *, target_alias, command):
        self.calls.append((target_alias, command))
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


def snapshot(commands=K10_COMMANDS):
    return RuntimeCapabilitySnapshot(
        "cleaner",
        "K10+",
        commands,
        NOW,
        timedelta(minutes=5),
    )


def request(command, *, dry_run=True):
    return RobotOperationRequest(
        f"op-{command.value.replace('_', '-')}",
        "cleaner",
        command,
        NOW,
        dry_run,
    )


def test_robot_state_normalizes_official_working_charging_and_task_status():
    state = normalize_robot_state(
        {
            "workingStatus": "Charging",
            "taskType": "backToCharge",
            "battery": 74,
            "waterBaseBattery": 63,
            "onlineStatus": "online",
        },
        observed_at=NOW,
    )
    assert state.battery_percent == 74
    assert state.working_status is RobotWorkingStatus.CHARGING
    assert state.charging_status is RobotChargingStatus.CHARGING
    assert state.task_status is RobotTaskStatus.BACK_TO_CHARGE
    assert state.online is True
    assert state.water_base_battery_percent == 63
    assert state.quality is Quality.GOOD

    unknown = normalize_robot_state(
        {
            "workingStatus": "NewFirmwareState",
            "taskType": "newTask",
            "battery": 101,
        },
        observed_at=NOW,
    )
    assert unknown.battery_percent is None
    assert unknown.working_status is RobotWorkingStatus.UNKNOWN
    assert unknown.charging_status is RobotChargingStatus.UNKNOWN
    assert unknown.task_status is RobotTaskStatus.UNKNOWN
    assert unknown.unknown_values == ("workingStatus", "taskType")
    assert unknown.quality is Quality.UNKNOWN
    assert "NewFirmwareState" not in repr(unknown)


def test_only_documented_commands_are_admitted_for_exact_device_family():
    assert official_commands_for("K10+") == K10_COMMANDS
    assert official_commands_for("Mini Robot Vacuum K10+") == K10_COMMANDS
    assert official_commands_for("Floor Cleaning Robot S10") == frozenset(
        {RobotCommand.START_CLEAN, RobotCommand.PAUSE, RobotCommand.DOCK}
    )
    assert official_commands_for("Future Cleaner") == frozenset()

    with pytest.raises(ValueError, match="official-confirmed"):
        RuntimeCapabilitySnapshot(
            "cleaner",
            "K10+",
            frozenset({RobotCommand.PAUSE}),
            NOW,
            timedelta(minutes=5),
        )


def test_s10_start_clean_has_typed_official_payload_but_dry_run_only():
    capability = RuntimeCapabilitySnapshot(
        "cleaner",
        "Floor Cleaning Robot S10",
        frozenset({RobotCommand.START_CLEAN}),
        NOW,
        timedelta(minutes=5),
    )
    transport = FakeTransport()
    request_value = RobotOperationRequest(
        "op-start-clean",
        "cleaner",
        RobotCommand.START_CLEAN,
        NOW,
        True,
        S10CleanParameters("sweep_mop", 2, 1),
    )
    result = RobotOperationAdapter(
        capability, transport=transport, clock=lambda: NOW
    ).execute(request_value)

    assert result.dispatch.status is DispatchStatus.DRY_RUN
    assert result.vendor_command.payload() == {
        "command": "startClean",
        "parameter": {
            "action": "sweep_mop",
            "param": {"fanLevel": 2, "waterLevel": 1, "times": 1},
        },
        "commandType": "command",
    }
    assert transport.calls == []

    with pytest.raises(ValueError, match="times must be 1"):
        S10CleanParameters("sweep_mop", 2, 1, times=2)


def test_capability_gated_dry_run_never_dispatches_or_reads():
    transport = FakeTransport()
    reader = FakeReader(
        RobotState(
            80,
            RobotWorkingStatus.STANDBY,
            RobotChargingStatus.NOT_CHARGING,
            RobotTaskStatus.NONE,
            True,
            NOW,
        )
    )
    result = RobotOperationAdapter(
        snapshot(), transport=transport, state_reader=reader, clock=lambda: NOW
    ).execute(request(RobotCommand.DOCK))

    assert result.dispatch.status is DispatchStatus.DRY_RUN
    assert result.dispatch.attempt_number == 0
    assert result.verification.status is VerificationStatus.NOT_ATTEMPTED
    assert result.outcome is OperationOutcome.PLANNED
    assert transport.calls == []
    assert reader.calls == []


def test_qualified_dispatch_and_readback_each_happen_once():
    transport = FakeTransport()
    reader = FakeReader(
        RobotState(
            80,
            RobotWorkingStatus.RETURNING_TO_DOCK,
            RobotChargingStatus.RETURNING_TO_DOCK,
            RobotTaskStatus.NONE,
            True,
            NOW,
        )
    )
    result = RobotOperationAdapter(
        snapshot(), transport=transport, state_reader=reader, clock=lambda: NOW
    ).execute(request(RobotCommand.DOCK, dry_run=False))

    assert len(transport.calls) == 1
    assert reader.calls == ["cleaner"]
    assert result.verification.status is VerificationStatus.MATCHED
    assert result.outcome is OperationOutcome.COMPLETED


def test_timeout_never_redispatches_or_reads_back():
    transport = FakeTransport(SwitchBotOperationTimeout())
    reader = FakeReader(
        RobotState(
            80,
            RobotWorkingStatus.STANDBY,
            RobotChargingStatus.NOT_CHARGING,
            RobotTaskStatus.NONE,
            True,
            NOW,
        )
    )
    result = RobotOperationAdapter(
        snapshot(), transport=transport, state_reader=reader, clock=lambda: NOW
    ).execute(request(RobotCommand.START, dry_run=False))

    assert len(transport.calls) == 1
    assert reader.calls == []
    assert result.dispatch.status is DispatchStatus.TIMEOUT
    assert result.outcome is OperationOutcome.UNKNOWN


@pytest.mark.parametrize(
    "state",
    [
        RobotState(
            80,
            RobotWorkingStatus.RETURNING_TO_DOCK,
            RobotChargingStatus.RETURNING_TO_DOCK,
            RobotTaskStatus.NONE,
            True,
            NOW - timedelta(seconds=1),
        ),
        RobotState(
            80,
            RobotWorkingStatus.RETURNING_TO_DOCK,
            RobotChargingStatus.RETURNING_TO_DOCK,
            RobotTaskStatus.NONE,
            True,
            NOW,
            quality=Quality.UNKNOWN,
        ),
    ],
)
def test_stale_or_insufficient_quality_readback_cannot_complete(state):
    result = RobotOperationAdapter(
        snapshot(),
        transport=FakeTransport(),
        state_reader=FakeReader(state),
        clock=lambda: NOW,
    ).execute(request(RobotCommand.DOCK, dry_run=False))

    assert result.verification.status is VerificationStatus.UNAVAILABLE
    assert result.outcome is OperationOutcome.UNKNOWN


def test_non_device_features_have_explicit_safe_boundaries():
    for feature in (
        SwitchBotFeature.SCHEDULES,
        SwitchBotFeature.REPORTS,
        SwitchBotFeature.ROOMS,
    ):
        assert feature_support(feature).disposition is FeatureDisposition.LOCAL_HESTIA
    assert (
        feature_support(SwitchBotFeature.REMOTE_CONTROL).disposition
        is FeatureDisposition.UNSUPPORTED
    )
