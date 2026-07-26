"""Thin vendor bridges for the common Execution coordinator."""

from __future__ import annotations

from collections.abc import Callable

from hedp.adapters.ecocute.operation import (
    EcoCuteOperationAdapter,
    EcoCuteSetCommand,
)
from hedp.adapters.qrio.operation import (
    QrioCommand,
    QrioOperationAdapter,
    QrioOperationRequest,
)

from .execution import AdapterExecutionResult, ExecutionOutcome, Intent


class QrioExecutionPort:
    def __init__(self, adapter: QrioOperationAdapter) -> None:
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
    def __init__(
        self,
        adapter: EcoCuteOperationAdapter,
        command_builder: Callable[[Intent], EcoCuteSetCommand],
    ) -> None:
        self._adapter = adapter
        self._command_builder = command_builder

    def execute(self, intent: Intent) -> AdapterExecutionResult:
        result = self._adapter.execute(self._command_builder(intent))
        return AdapterExecutionResult(
            dispatch_status=result.dispatch.status.value,
            verification_status=result.verification.status.value,
            outcome=ExecutionOutcome(result.outcome.value),
        )
