"""Long-lived, low-latency light command session for a local HESTIA UI.

The session owns no credentials and performs no discovery or read-back.  It
keeps the already-constructed ExecutionCoordinator and transport alive.  Tap
commands dispatch immediately.  Rapid slider commands are serialized and
coalesced so only the newest unsent value reaches the common ExecutionGate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Condition, Lock, Thread
from typing import Callable

from hedp.operations.execution import (
    Authorization,
    ExecutionCoordinator,
    ExecutionMode,
    ExecutionResult,
)
from hedp.operations.shadow_execution import Intent, StateEvidence


@dataclass(frozen=True)
class PreparedLightOperation:
    """A complete, short-lived operation prepared by the local UI boundary."""

    intent: Intent
    evidence: StateEvidence
    authorization: Authorization
    evaluated_at: datetime
    manual_override_cooldown: timedelta = timedelta(0)


class FastLightControlSession:
    """Reuse one live execution path and coalesce high-frequency slider input."""

    def __init__(
        self,
        coordinator: ExecutionCoordinator,
        *,
        debounce_seconds: float = 0.075,
        result_callback: Callable[[ExecutionResult], None] | None = None,
    ) -> None:
        if not isinstance(coordinator, ExecutionCoordinator):
            raise TypeError("coordinator must be an ExecutionCoordinator")
        if not 0.01 <= debounce_seconds <= 0.25:
            raise ValueError("debounce_seconds must be from 0.01 to 0.25")
        self._coordinator = coordinator
        self._debounce_seconds = debounce_seconds
        self._result_callback = result_callback
        self._condition = Condition()
        self._send_lock = Lock()
        self._pending: PreparedLightOperation | None = None
        self._generation = 0
        self._closed = False
        self._sending = False
        self._worker = Thread(
            target=self._run,
            name="hestia-light-slider",
            daemon=True,
        )
        self._worker.start()

    def send_immediately(self, operation: PreparedLightOperation) -> ExecutionResult:
        """Dispatch a tap/button operation without a network pre-read."""

        self._require_open()
        result = self._execute(operation)
        self._notify(result)
        return result

    def submit_latest(self, operation: PreparedLightOperation) -> None:
        """Queue a slider value, replacing any older value not yet sent."""

        if not isinstance(operation, PreparedLightOperation):
            raise TypeError("operation must be PreparedLightOperation")
        with self._condition:
            if self._closed:
                raise RuntimeError("light control session is closed")
            self._pending = operation
            self._generation += 1
            self._condition.notify_all()

    def wait_idle(self, timeout_seconds: float = 1.0) -> bool:
        """Wait until no slider command is pending or being sent."""

        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        with self._condition:
            return self._condition.wait_for(
                lambda: self._pending is None and not self._sending,
                timeout=timeout_seconds,
            )

    def close(self, *, discard_pending: bool = True) -> None:
        """Stop the worker without sending unexpected commands during shutdown."""

        with self._condition:
            if discard_pending:
                self._pending = None
            self._closed = True
            self._condition.notify_all()
        self._worker.join(timeout=1.0)

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(
                    lambda: self._closed or self._pending is not None
                )
                if self._closed:
                    return
                generation = self._generation
                self._condition.wait(timeout=self._debounce_seconds)
                if self._closed:
                    return
                if generation != self._generation:
                    continue
                operation = self._pending
                self._pending = None
                self._sending = operation is not None
            if operation is None:
                continue
            try:
                result = self._execute(operation)
                self._notify(result)
            finally:
                with self._condition:
                    self._sending = False
                    self._condition.notify_all()

    def _execute(self, operation: PreparedLightOperation) -> ExecutionResult:
        if not isinstance(operation, PreparedLightOperation):
            raise TypeError("operation must be PreparedLightOperation")
        with self._send_lock:
            return self._coordinator.execute(
                operation.intent,
                evidence=operation.evidence,
                authorization=operation.authorization,
                evaluated_at=operation.evaluated_at,
                mode=ExecutionMode.LIVE,
                manual_override_cooldown=operation.manual_override_cooldown,
            )

    def _notify(self, result: ExecutionResult) -> None:
        if self._result_callback is not None:
            try:
                self._result_callback(result)
            except Exception:
                # UI reporting must never terminate the command worker.
                return

    def _require_open(self) -> None:
        with self._condition:
            if self._closed:
                raise RuntimeError("light control session is closed")
