from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from hedp.adapters.miele.operation import (
    MieleCapabilitySnapshot,
    MieleCommand,
    MieleDispatchReceipt,
    MieleDispatchReceiptStatus,
    MieleDryRunOutcome,
    MieleOperationGate,
    MieleProgramReadback,
    MieleReadbackUnavailable,
    MieleStartVerificationCapability,
    MieleStartVerificationGate,
    MieleStartVerificationOutcome,
    StartScheduledProgramRequest,
    scheduled_program_execution_capability,
)
from hedp.observations import Quality
from hedp.operations.execution import (
    Authorization,
    ExecutionCoordinator,
    ExecutionOutcome,
)
from hedp.operations.shadow_execution import EvidenceQuality, Intent, StateEvidence


NOW = datetime(2026, 7, 27, 7, tzinfo=timezone.utc)
FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "miele" / "scheduled_program_start_contract_v1.json"
)


class FakeReadback:
    def __init__(self, value: MieleProgramReadback) -> None:
        self.value = value
        self.calls: list[str] = []

    def read_program_state(self, target_alias: str) -> MieleProgramReadback:
        self.calls.append(target_alias)
        return self.value


def _request() -> StartScheduledProgramRequest:
    return StartScheduledProgramRequest("op-1", "laundry", NOW - timedelta(seconds=2))


def _snapshot(
    commands: frozenset[MieleCommand] = frozenset(
        {MieleCommand.START_SCHEDULED_PROGRAM}
    ),
) -> MieleCapabilitySnapshot:
    return MieleCapabilitySnapshot(
        target_alias="laundry",
        supported_commands=commands,
        observed_at=NOW - timedelta(seconds=10),
        max_age=timedelta(minutes=5),
        maximum_readback_age=timedelta(minutes=2),
        startable_status_codes=frozenset({5}),
    )


def _readback(*, quality: Quality = Quality.GOOD) -> MieleProgramReadback:
    return MieleProgramReadback(
        target_alias="laundry",
        observed_at=NOW - timedelta(seconds=5),
        quality=quality,
        status_code=5 if quality is Quality.GOOD else None,
        program_id=24 if quality is Quality.GOOD else None,
    )


def test_start_scheduled_program_is_typed_and_dry_run_only() -> None:
    port = FakeReadback(_readback())

    result = MieleOperationGate(_snapshot(), port).assess(
        _request(),
        evaluated_at=NOW,
    )

    assert result.request.command is MieleCommand.START_SCHEDULED_PROGRAM
    assert result.outcome is MieleDryRunOutcome.WOULD_DISPATCH
    assert result.reason_code == "conditions_satisfied"
    assert result.dispatch_attempted is False
    assert port.calls == ["laundry"]


def test_unadvertised_command_blocks_before_readback() -> None:
    port = FakeReadback(_readback())

    result = MieleOperationGate(_snapshot(frozenset()), port).assess(
        _request(),
        evaluated_at=NOW,
    )

    assert result.outcome is MieleDryRunOutcome.WOULD_BLOCK
    assert result.reason_code == "command_not_advertised"
    assert port.calls == []


def test_stale_or_bad_readback_is_indeterminate_not_success() -> None:
    port = FakeReadback(_readback(quality=Quality.UNKNOWN))
    result = MieleOperationGate(_snapshot(), port).assess(
        _request(),
        evaluated_at=NOW,
    )

    assert result.outcome is MieleDryRunOutcome.INDETERMINATE
    assert result.reason_code == "readback_quality_insufficient"
    assert result.dispatch_attempted is False


def test_missing_scheduled_program_is_not_treated_as_dispatchable() -> None:
    readback = MieleProgramReadback(
        target_alias="laundry",
        observed_at=NOW - timedelta(seconds=5),
        quality=Quality.GOOD,
        status_code=5,
        program_id=None,
    )

    result = MieleOperationGate(_snapshot(), FakeReadback(readback)).assess(
        _request(),
        evaluated_at=NOW,
    )

    assert result.outcome is MieleDryRunOutcome.INDETERMINATE
    assert result.reason_code == "scheduled_program_missing"
    assert result.dispatch_attempted is False


def test_non_startable_status_is_blocked_and_missing_status_evidence_is_unknown() -> (
    None
):
    port = FakeReadback(
        MieleProgramReadback(
            target_alias="laundry",
            observed_at=NOW - timedelta(seconds=5),
            quality=Quality.GOOD,
            status_code=6,
            program_id=24,
        )
    )
    result = MieleOperationGate(_snapshot(), port).assess(
        _request(),
        evaluated_at=NOW,
    )
    assert result.outcome is MieleDryRunOutcome.WOULD_BLOCK
    assert result.reason_code == "status_not_startable"

    no_status_contract = MieleCapabilitySnapshot(
        target_alias="laundry",
        supported_commands=frozenset({MieleCommand.START_SCHEDULED_PROGRAM}),
        observed_at=NOW - timedelta(seconds=10),
        max_age=timedelta(minutes=5),
        maximum_readback_age=timedelta(minutes=2),
    )
    result = MieleOperationGate(no_status_contract, FakeReadback(_readback())).assess(
        _request(),
        evaluated_at=NOW,
    )
    assert result.outcome is MieleDryRunOutcome.INDETERMINATE
    assert result.reason_code == "startable_status_capability_missing"


def test_sanitized_readback_failure_is_indeterminate() -> None:
    class UnavailableReadback:
        def read_program_state(self, target_alias: str) -> MieleProgramReadback:
            raise MieleReadbackUnavailable("readback-unavailable")

    result = MieleOperationGate(_snapshot(), UnavailableReadback()).assess(
        _request(),
        evaluated_at=NOW,
    )

    assert result.outcome is MieleDryRunOutcome.INDETERMINATE
    assert result.reason_code == "readback_unavailable"
    assert result.dispatch_attempted is False


def test_contract_has_no_write_transport_or_payload_fields() -> None:
    request = _request()

    assert not hasattr(request, "url")
    assert not hasattr(request, "endpoint")
    assert not hasattr(request, "payload")
    assert not hasattr(MieleOperationGate, "execute")
    assert not hasattr(MieleOperationGate, "dispatch")


def test_common_execution_gate_connects_in_shadow_without_a_miele_writer() -> None:
    snapshot = _snapshot()
    coordinator = ExecutionCoordinator((scheduled_program_execution_capability(snapshot),))
    intent = Intent(
        operation_id="op-1",
        requested_at=NOW - timedelta(seconds=2),
        expires_at=NOW + timedelta(minutes=1),
        requester="fixture-user",
        reason="anonymous operation fixture",
        target_alias="laundry",
        capability="miele-start-scheduled-program",
        desired_state=MieleCommand.START_SCHEDULED_PROGRAM,
        priority=1,
        control_owner="miele",
        correlation_id="decision-1",
    )
    authorization = Authorization(
        operation_id="op-1",
        requester="fixture-user",
        target_alias="laundry",
        capability="miele-start-scheduled-program",
        desired_state=MieleCommand.START_SCHEDULED_PROGRAM,
        granted_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=1),
    )
    evidence = StateEvidence(
        target_alias="laundry",
        capability="miele-start-scheduled-program",
        observed_at=NOW - timedelta(seconds=5),
        quality=EvidenceQuality.GOOD,
        current_state="scheduled-program-present",
    )

    result = coordinator.execute(
        intent,
        evidence=evidence,
        authorization=authorization,
        evaluated_at=NOW,
    )

    assert result.outcome is ExecutionOutcome.WOULD_DISPATCH
    assert result.dispatch_attempted is False
    assert result.adapter_result is None


def test_post_dispatch_verification_requires_receipt_and_observed_status_contract() -> (
    None
):
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    capability = MieleStartVerificationCapability(
        target_alias=fixture["target_alias"],
        observed_at=NOW - timedelta(seconds=10),
        max_age=timedelta(seconds=fixture["verification"]["max_age_seconds"]),
        maximum_readback_age=timedelta(
            seconds=fixture["verification"]["maximum_readback_age_seconds"]
        ),
        started_status_codes=frozenset(fixture["verification"]["started_status_codes"]),
    )
    receipt = MieleDispatchReceipt(
        target_alias="laundry",
        status=MieleDispatchReceiptStatus.ACCEPTED,
        observed_at=NOW - timedelta(seconds=2),
    )
    post_readback = MieleProgramReadback(
        target_alias="laundry",
        observed_at=NOW - timedelta(seconds=3),
        quality=Quality.GOOD,
        status_code=fixture["post_dispatch_readback"]["status_code"],
        program_id=fixture["post_dispatch_readback"]["program_id"],
    )

    result = MieleStartVerificationGate(capability).assess(
        receipt=receipt,
        post_dispatch_readback=post_readback,
        evaluated_at=NOW,
    )

    assert result.outcome is MieleStartVerificationOutcome.MATCHED
    assert result.reason_code == "post_start_status_matched"


def test_post_dispatch_verification_remains_indeterminate_without_qualified_codes() -> (
    None
):
    capability = MieleStartVerificationCapability(
        target_alias="laundry",
        observed_at=NOW - timedelta(seconds=10),
        max_age=timedelta(minutes=5),
        maximum_readback_age=timedelta(minutes=2),
    )

    result = MieleStartVerificationGate(capability).assess(
        receipt=None,
        post_dispatch_readback=None,
        evaluated_at=NOW,
    )

    assert result.outcome is MieleStartVerificationOutcome.INDETERMINATE
    assert result.reason_code == "started_status_capability_missing"
