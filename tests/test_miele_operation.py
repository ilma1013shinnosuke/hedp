from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hedp.adapters.miele import (
    MieleCapabilitySnapshot,
    MieleCommand,
    MieleDryRunOutcome,
    MieleOperationGate,
    MieleProgramReadback,
    MieleReadbackUnavailable,
    StartScheduledProgramRequest,
)
from hedp.observations import Quality


NOW = datetime(2026, 7, 27, 7, tzinfo=timezone.utc)


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
