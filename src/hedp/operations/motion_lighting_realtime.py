"""First real-time consumer proving SwitchBot-to-lighting event delivery."""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic

from hedp.adapters.smartledz.operation import (
    SmartLedzDryRun,
    SmartLedzDryRunPlanner,
)
from hedp.adapters.switchbot.secondary_state import SecondaryDeviceObservation
from hedp.events import EventEnvelope
from hedp.intelligence.motion_lighting import (
    LightingSelectionKind,
    MotionLightingAutomation,
    MotionLightingDecision,
)


class MotionLightingRealtimeConsumer:
    """Route SwitchBot events to Layer 3 without waiting for persistence."""

    def __init__(
        self,
        automation: MotionLightingAutomation,
        decision_sink: Callable[[MotionLightingDecision], None],
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._automation = automation
        self._decision_sink = decision_sink
        self._clock = clock

    def __call__(
        self, event: EventEnvelope[SecondaryDeviceObservation]
    ) -> None:
        for decision in self._automation.process(
            event.payload,
            event_id=event.event_id,
            monotonic_seconds=self._clock(),
        ):
            self._decision_sink(decision)

    def tick(self) -> None:
        for decision in self._automation.tick(self._clock()):
            self._decision_sink(decision)

    def manual_override(self) -> None:
        self._automation.manual_override()


def plan_smartledz_motion_decision(
    decision: MotionLightingDecision,
    planner: SmartLedzDryRunPlanner,
) -> SmartLedzDryRun:
    """Translate a Layer 3 selection into a Layer 4 dry-run plan."""

    selection = decision.selection
    if selection.kind is LightingSelectionKind.SCENE:
        return planner.scene_run(
            group_alias=selection.target_alias,
            scene_alias=selection.selection_alias,
        )
    return planner.schedule_select(
        group_alias=selection.target_alias,
        schedule_alias=selection.selection_alias,
    )
