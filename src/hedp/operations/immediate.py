"""Reusable, low-latency command session for HESTIA operation entry points.

The session keeps an already-built :class:`ExecutionCoordinator` alive.  A
button/tap command enters the common ExecutionGate synchronously.  Rapid
continuous input may be coalesced for a very short, bounded interval so only
the newest unsent value is dispatched.

There is deliberately no database, discovery, read-back, or durable command
queue here.  Those concerns must not delay dispatch start, and an old command
must never be replayed after process restart.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Condition, Lock, Thread
from typing import Callable

from .execution import (
    Authorization,
    ExecutionCoordinator,
    ExecutionMode,
    ExecutionResult,
)
from .shadow_execution import Intent, StateEvidence


@dataclass(frozen=True)
class PreparedOperation:
    """A fully prepared operation for one immediate execution attempt."""

    intent: Intent
    evidence: StateEvidence
    authorization: Authorization
    evaluated_at: datetime
    manual_override_cooldown: timedelta = timedelta(0)


class ImmediateExecutionSession:
    """Reuse one Execution path and coalesce high-frequency continuous input."""

    def __init__(
        self,
        coordinator: ExecutionCoordinator,
        *,
        mode: ExecutionMode = ExecutionMode.LIVE,
        debounce_seconds: float = 0.075,
        result_callback: Callable[[ExecutionResult], None] | None = None,
        worker_name: str = "hestia-immediate-operation",
    ) -> None:
        if not isinstance(coordinator, ExecutionCoordinator):
            raise TypeError("coordinator must be an ExecutionCoordinator")
        if not isinstance(mode, ExecutionMode):
            raise TypeError("mode must be an ExecutionMode")
        if not 0.01 <= debounce_seconds <= 0.25:
            raise ValueError("debounce_seconds must be from 0.01 to 0.25")
        if not isinstance(worker_name, str) or not worker_name:
            raise ValueError("worker_name must not be empty")
        self._coordinator = coordinator
        self._mode = mode
        self._debounce_seconds = debounce_seconds
        self._result_callback = result_callback
        self._condition = Condition()
        self._send_lock = Lock()
        self._pending: PreparedOperation | None = None
        self._generation = 0
        self._closed = False
        self._sending = False
        self._worker = Thread(
            target=self._run,
            name=worker_name,
            daemon=True,
        )
        self._worker.start()

    def send_immediately(self, operation: PreparedOperation) -> ExecutionResult:
        """Enter the common ExecutionGate without discovery or persistence."""

        self._require_open()
        result = self._execute(operation)
        self._notify(result)
        return result

    def submit_latest(self, operation: PreparedOperation) -> None:
        """Queue a continuous value, replacing an older value not yet sent."""

        if not isinstance(operation, PreparedOperation):
            raise TypeError("operation must be PreparedOperation")
        with self._condition:
            if self._closed:
                raise RuntimeError("immediate execution session is closed")
            self._pending = operation
            self._generation += 1
            self._condition.notify_all()

    def wait_idle(self, timeout_seconds: float = 1.0) -> bool:
        """Wait until no coalesced command is pending or being sent."""

        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        with self._condition:
            return self._condition.wait_for(
                lambda: self._pending is None and not self._sending,
                timeout=timeout_seconds,
            )

    def close(self, *, discard_pending: bool = True) -> None:
        """Stop without replaying an unsent command during shutdown."""

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

    def _execute(self, operation: PreparedOperation) -> ExecutionResult:
        if not isinstance(operation, PreparedOperation):
            raise TypeError("operation must be PreparedOperation")
        with self._send_lock:
            return self._coordinator.execute(
                operation.intent,
                evidence=operation.evidence,
                authorization=operation.authorization,
                evaluated_at=operation.evaluated_at,
                mode=self._mode,
                manual_override_cooldown=operation.manual_override_cooldown,
            )

    def _notify(self, result: ExecutionResult) -> None:
        if self._result_callback is not None:
            try:
                self._result_callback(result)
            except Exception:
                # Reporting must never terminate the command worker.
                return

    def _require_open(self) -> None:
        with self._condition:
            if self._closed:
                raise RuntimeError("immediate execution session is closed")
