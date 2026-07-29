"""Offline Smart LEDZ appearance-transition planning and fixture execution.

The recovered Smart LEDZ material does not yet prove a live wire command for
arbitrary brightness and colour-temperature changes.  This module therefore
builds and validates the complete low-latency transition boundary, but only a
fixture port can dispatch its steps.  A live port must not be added until its
wire shape and read-back are qualified with anonymous fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Callable, Protocol

from hedp.operations.execution import (
    AdapterExecutionResult,
    ExecutionCapability,
    ExecutionOutcome,
)
from hedp.operations.shadow_execution import Intent


SMARTLEDZ_TRANSITION_CAPABILITY = "smartledz-appearance-transition"


@dataclass(frozen=True)
class SmartLedzAppearance:
    """One normalized light appearance at 1% and 100 K resolution."""

    brightness_pct: int
    color_temperature_kelvin: int

    def __post_init__(self) -> None:
        if isinstance(self.brightness_pct, bool) or not isinstance(
            self.brightness_pct, int
        ):
            raise TypeError("brightness_pct must be an integer")
        if not 0 <= self.brightness_pct <= 100:
            raise ValueError("brightness_pct must be from 0 to 100")
        if isinstance(self.color_temperature_kelvin, bool) or not isinstance(
            self.color_temperature_kelvin, int
        ):
            raise TypeError("color_temperature_kelvin must be an integer")
        if not 1_000 <= self.color_temperature_kelvin <= 10_000:
            raise ValueError(
                "color_temperature_kelvin must be from 1000 to 10000"
            )
        if self.color_temperature_kelvin % 100:
            raise ValueError("color_temperature_kelvin must use 100 K steps")


@dataclass(frozen=True)
class SmartLedzTransitionRequest:
    """A typed request produced by UI or Layer 3, never by the adapter."""

    target_alias: str
    current: SmartLedzAppearance
    target: SmartLedzAppearance
    duration: timedelta
    minimum_command_interval: timedelta = timedelta(milliseconds=200)
    max_steps: int = 300

    def __post_init__(self) -> None:
        if not isinstance(self.target_alias, str) or not self.target_alias:
            raise ValueError("target_alias must not be empty")
        if not isinstance(self.current, SmartLedzAppearance):
            raise TypeError("current must be a SmartLedzAppearance")
        if not isinstance(self.target, SmartLedzAppearance):
            raise TypeError("target must be a SmartLedzAppearance")
        if (
            not isinstance(self.duration, timedelta)
            or self.duration <= timedelta(0)
            or self.duration > timedelta(hours=1)
        ):
            raise ValueError("duration must be greater than 0 and at most 1 hour")
        if (
            not isinstance(self.minimum_command_interval, timedelta)
            or self.minimum_command_interval < timedelta(milliseconds=100)
            or self.minimum_command_interval > timedelta(seconds=5)
        ):
            raise ValueError(
                "minimum_command_interval must be from 100 ms to 5 seconds"
            )
        if isinstance(self.max_steps, bool) or not isinstance(self.max_steps, int):
            raise TypeError("max_steps must be an integer")
        if not 1 <= self.max_steps <= 1_000:
            raise ValueError("max_steps must be from 1 to 1000")


@dataclass(frozen=True)
class SmartLedzTransitionStep:
    """One due appearance.  Offset zero is dispatched immediately."""

    offset: timedelta
    appearance: SmartLedzAppearance


@dataclass(frozen=True)
class SmartLedzTransitionPlan:
    """Bounded, immutable sequence with no manufacturer identifier."""

    request: SmartLedzTransitionRequest
    steps: tuple[SmartLedzTransitionStep, ...]

    @property
    def is_noop(self) -> bool:
        return not self.steps


def plan_smartledz_transition(
    request: SmartLedzTransitionRequest,
) -> SmartLedzTransitionPlan:
    """Create a bounded plan whose first changed value is due immediately."""

    if not isinstance(request, SmartLedzTransitionRequest):
        raise TypeError("request must be a SmartLedzTransitionRequest")
    if request.current == request.target:
        return SmartLedzTransitionPlan(request, ())

    brightness_changes = abs(
        request.target.brightness_pct - request.current.brightness_pct
    )
    temperature_changes = abs(
        request.target.color_temperature_kelvin
        - request.current.color_temperature_kelvin
    ) // 100
    desired_steps = max(brightness_changes, temperature_changes, 1)
    interval_budget = max(
        1,
        int(request.duration / request.minimum_command_interval) + 1,
    )
    step_count = min(desired_steps, interval_budget, request.max_steps)

    steps: list[SmartLedzTransitionStep] = []
    for index in range(1, step_count + 1):
        fraction = index / step_count
        brightness = round(
            request.current.brightness_pct
            + (
                request.target.brightness_pct
                - request.current.brightness_pct
            )
            * fraction
        )
        temperature = _round_to_100(
            request.current.color_temperature_kelvin
            + (
                request.target.color_temperature_kelvin
                - request.current.color_temperature_kelvin
            )
            * fraction
        )
        appearance = SmartLedzAppearance(brightness, temperature)
        if step_count == 1:
            offset = timedelta(0)
        else:
            offset = request.duration * ((index - 1) / (step_count - 1))
        step = SmartLedzTransitionStep(offset, appearance)
        if not steps or steps[-1].appearance != appearance:
            steps.append(step)

    if steps[-1].appearance != request.target:
        steps.append(SmartLedzTransitionStep(request.duration, request.target))
    elif steps[-1].offset != request.duration and len(steps) > 1:
        steps[-1] = SmartLedzTransitionStep(request.duration, request.target)
    return SmartLedzTransitionPlan(request, tuple(steps))


class SmartLedzTransitionSink(Protocol):
    """Fixture-only boundary until the direct wire schema is qualified."""

    fixture_only: bool

    def send(self, step: SmartLedzTransitionStep) -> None: ...


class ImmediateSmartLedzTransitionSession:
    """Start now, coalesce overdue steps, and never persist/replay a plan."""

    def __init__(
        self,
        target_alias: str,
        sink: SmartLedzTransitionSink,
    ) -> None:
        if not isinstance(target_alias, str) or not target_alias:
            raise ValueError("target_alias must not be empty")
        if getattr(sink, "fixture_only", False) is not True:
            raise TypeError("a fixture-only transition sink is required")
        self._target_alias = target_alias
        self._sink = sink
        self._plan: SmartLedzTransitionPlan | None = None
        self._started_at = 0.0
        self._next_index = 0
        self._closed = False

    @property
    def pending_count(self) -> int:
        if self._plan is None:
            return 0
        return len(self._plan.steps) - self._next_index

    def submit(self, plan: SmartLedzTransitionPlan, *, now: float) -> None:
        """Replace any unsent plan and dispatch its first changed value now."""

        self._require_open()
        if not isinstance(plan, SmartLedzTransitionPlan):
            raise TypeError("plan must be a SmartLedzTransitionPlan")
        if plan.request.target_alias != self._target_alias:
            raise ValueError("transition target does not match the session")
        if now < 0:
            raise ValueError("now must not be negative")
        self._plan = plan
        self._started_at = now
        self._next_index = 0
        if plan.steps:
            self._sink.send(plan.steps[0])
            self._next_index = 1
        self._clear_if_finished()

    def dispatch_due(self, *, now: float) -> int:
        """Dispatch only the newest due step to avoid a command backlog."""

        self._require_open()
        if now < 0:
            raise ValueError("now must not be negative")
        plan = self._plan
        if plan is None:
            return 0
        elapsed = now - self._started_at
        if elapsed < 0:
            raise ValueError("now precedes the transition start")
        newest_due: SmartLedzTransitionStep | None = None
        while self._next_index < len(plan.steps):
            candidate = plan.steps[self._next_index]
            if candidate.offset.total_seconds() > elapsed:
                break
            newest_due = candidate
            self._next_index += 1
        if newest_due is not None:
            self._sink.send(newest_due)
        self._clear_if_finished()
        return int(newest_due is not None)

    def cancel(self) -> None:
        """Discard unsent steps after a newer user or physical operation."""

        self._plan = None
        self._next_index = 0

    def close(self) -> None:
        self.cancel()
        self._closed = True

    def _clear_if_finished(self) -> None:
        if self._plan is not None and self._next_index >= len(self._plan.steps):
            self._plan = None
            self._next_index = 0

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("transition session is closed")


class SmartLedzTransitionFixturePort:
    """ExecutionPort that proves Gate-to-immediate-start without live I/O."""

    fixture_only = True

    def __init__(
        self,
        session: ImmediateSmartLedzTransitionSession,
        *,
        clock: Callable[[], float],
    ) -> None:
        self._session = session
        self._clock = clock

    def execute(self, intent: Intent) -> AdapterExecutionResult:
        plan = intent.desired_state
        if not isinstance(plan, SmartLedzTransitionPlan):
            return AdapterExecutionResult(
                "rejected",
                "not_started",
                ExecutionOutcome.FAILED,
            )
        self._session.submit(plan, now=self._clock())
        return AdapterExecutionResult(
            "accepted",
            "pending",
            ExecutionOutcome.PENDING_VERIFICATION,
        )


def transition_execution_capability(
    *,
    target_alias: str,
    control_owner: str,
    maximum_state_age: timedelta,
) -> ExecutionCapability:
    """Return a strict capability for one configured Smart LEDZ target."""

    def valid(value: object) -> bool:
        return (
            isinstance(value, SmartLedzTransitionPlan)
            and value.request.target_alias == target_alias
            and not value.is_noop
        )

    return ExecutionCapability(
        target_alias,
        SMARTLEDZ_TRANSITION_CAPABILITY,
        control_owner,
        (),
        maximum_state_age,
        desired_state_validator=valid,
    )


def _round_to_100(value: float) -> int:
    return int(round(value / 100.0) * 100)
