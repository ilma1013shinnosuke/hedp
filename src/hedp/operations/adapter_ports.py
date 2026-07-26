"""Fixture-only vendor bridges for the common Execution coordinator.

These bridges are deliberately not production adapters.  They accept only
objects explicitly marked as fixture-only, so the existing directly callable
Qrio and EcoCute operation adapters cannot be connected to the coordinator by
accident.  A future live bridge requires a separate durable Execution design;
direct adapter execution is not an approved production entry point.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from hedp.adapters.ecocute.operation import (
    EcoCuteOperationResult,
    EcoCuteSetCommand,
)
from hedp.adapters.qrio.operation import (
    QrioCommand,
    QrioOperationResult,
    QrioOperationRequest,
)

from .execution import AdapterExecutionResult, ExecutionOutcome, Intent


class FixtureQrioOperationAdapter(Protocol):
    fixture_only: bool

    def execute(self, request: QrioOperationRequest) -> QrioOperationResult: ...


class FixtureEcoCuteOperationAdapter(Protocol):
    fixture_only: bool

    def execute(self, command: EcoCuteSetCommand) -> EcoCuteOperationResult: ...


class QrioExecutionPort:
    """Translate an Intent for an explicitly marked Qrio fixture adapter."""

    fixture_only = True
    production_execution_enabled = False

    def __init__(self, adapter: FixtureQrioOperationAdapter) -> None:
        _require_fixture_adapter(adapter, "Qrio")
        self._adapter = adapter

    def execute(self, intent: Intent) -> AdapterExecutionResult:
        command = QrioCommand(intent.desired_state)
        result = self._adapter.execute(
            QrioOperationRequest(
                operation_id=intent.operation_id,
                target_alias=intent.target_alias,
                command=command,
                requested_at=intent.requested_at,
            )
        )
        return AdapterExecutionResult(
            dispatch_status=result.receipt.status.value,
            verification_status=result.verification.status.value,
            outcome=ExecutionOutcome(result.outcome.value),
        )


class EcoCuteExecutionPort:
    """Translate an Intent for an explicitly marked EcoCute fixture adapter."""

    fixture_only = True
    production_execution_enabled = False

    def __init__(
        self,
        adapter: FixtureEcoCuteOperationAdapter,
        command_builder: Callable[[Intent], EcoCuteSetCommand],
    ) -> None:
        _require_fixture_adapter(adapter, "EcoCute")
        self._adapter = adapter
        self._command_builder = command_builder

    def execute(self, intent: Intent) -> AdapterExecutionResult:
        result = self._adapter.execute(self._command_builder(intent))
        return AdapterExecutionResult(
            dispatch_status=result.dispatch.status.value,
            verification_status=result.verification.status.value,
            outcome=ExecutionOutcome(result.outcome.value),
        )


def _require_fixture_adapter(adapter: object, vendor: str) -> None:
    if getattr(adapter, "fixture_only", None) is not True:
        raise ValueError(f"{vendor} execution bridge requires a fixture-only adapter")
