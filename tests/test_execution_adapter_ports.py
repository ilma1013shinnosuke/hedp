from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from hedp.adapters.ecocute.operation import (
    DispatchStatus as EcoDispatchStatus,
    EcoCuteOperationAdapter,
    EcoCuteSetCommand,
    OperationOutcome as EcoOutcome,
    VerificationStatus as EcoVerificationStatus,
)
from hedp.adapters.qrio.operation import (
    DispatchStatus as QrioDispatchStatus,
    OperationOutcome as QrioOutcome,
    QrioCommand,
    QrioOperationAdapter,
    VerificationStatus as QrioVerificationStatus,
)
from hedp.operations.adapter_ports import EcoCuteExecutionPort, QrioExecutionPort
from hedp.operations.execution import ExecutionOutcome
from hedp.operations.shadow_execution import Intent


NOW = datetime(2026, 7, 26, 3, 0, tzinfo=timezone.utc)


def intent(**changes):
    values = {
        "operation_id": "operation-1",
        "requested_at": NOW,
        "expires_at": NOW + timedelta(minutes=1),
        "requester": "fixture-user",
        "reason": "anonymous fixture",
        "target_alias": "fixture-device",
        "capability": "fixture-operation",
        "desired_state": "lock",
        "priority": 1,
        "control_owner": "sumicore",
        "correlation_id": "decision-1",
    }
    values.update(changes)
    return Intent(**values)


def test_qrio_port_translates_intent_and_sanitized_result():
    class Adapter:
        fixture_only = True

        def __init__(self):
            self.requests = []

        def execute(self, request):
            self.requests.append(request)
            return SimpleNamespace(
                receipt=SimpleNamespace(status=QrioDispatchStatus.ACCEPTED),
                verification=SimpleNamespace(
                    status=QrioVerificationStatus.MATCHED
                ),
                outcome=QrioOutcome.COMPLETED,
            )

    adapter = Adapter()
    result = QrioExecutionPort(adapter).execute(intent())

    assert len(adapter.requests) == 1
    assert adapter.requests[0].command is QrioCommand.LOCK
    assert adapter.requests[0].operation_id == "operation-1"
    assert result.dispatch_status == "accepted"
    assert result.verification_status == "matched"
    assert result.outcome is ExecutionOutcome.COMPLETED


def test_ecocute_port_uses_explicit_command_builder_once():
    class Adapter:
        fixture_only = True

        def __init__(self):
            self.commands = []

        def execute(self, command):
            self.commands.append(command)
            return SimpleNamespace(
                dispatch=SimpleNamespace(status=EcoDispatchStatus.ACCEPTED),
                verification=SimpleNamespace(
                    status=EcoVerificationStatus.MATCHED
                ),
                outcome=EcoOutcome.COMPLETED,
            )

    built = []

    def command_builder(value):
        built.append(value.operation_id)
        return EcoCuteSetCommand(
            target_alias=value.target_alias,
            epc=0xB0,
            data=b"\x41",
            expected_readback=b"\x41",
        )

    adapter = Adapter()
    result = EcoCuteExecutionPort(adapter, command_builder).execute(
        intent(desired_state="start")
    )

    assert built == ["operation-1"]
    assert len(adapter.commands) == 1
    assert adapter.commands[0].epc == 0xB0
    assert result.dispatch_status == "accepted"
    assert result.verification_status == "matched"
    assert result.outcome is ExecutionOutcome.COMPLETED


@pytest.mark.parametrize(
    "port_factory",
    (
        lambda adapter: QrioExecutionPort(adapter),
        lambda adapter: EcoCuteExecutionPort(
            adapter,
            lambda value: EcoCuteSetCommand(
                target_alias=value.target_alias,
                epc=0xB0,
                data=b"\x41",
                expected_readback=b"\x41",
            ),
        ),
    ),
)
def test_vendor_bridge_rejects_unmarked_direct_adapter(port_factory):
    class UnmarkedAdapter:
        def execute(self, _):
            raise AssertionError("unmarked direct adapter must not be called")

    with pytest.raises(ValueError, match="fixture-only adapter"):
        port_factory(UnmarkedAdapter())


def test_existing_direct_operation_adapters_are_not_fixture_bridges():
    qrio_adapter = object.__new__(QrioOperationAdapter)
    ecocute_adapter = object.__new__(EcoCuteOperationAdapter)

    with pytest.raises(ValueError, match="Qrio.*fixture-only"):
        QrioExecutionPort(qrio_adapter)
    with pytest.raises(ValueError, match="EcoCute.*fixture-only"):
        EcoCuteExecutionPort(
            ecocute_adapter,
            lambda value: EcoCuteSetCommand(
                target_alias=value.target_alias,
                epc=0xB0,
                data=b"\x41",
                expected_readback=b"\x41",
            ),
        )
