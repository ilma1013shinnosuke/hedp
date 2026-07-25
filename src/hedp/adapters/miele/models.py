"""Common observation models for Miele read-only state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from hedp.observations import ObservationTime, ObservedValue, Quality


class CollectionSource(str, Enum):
    REST = "rest"
    SSE = "sse"


@dataclass(frozen=True)
class MieleObservation:
    target_ref: str = field(repr=False)
    source: CollectionSource
    status_code: ObservedValue[int]
    program_id: ObservedValue[int]
    program_type_code: ObservedValue[int]
    program_phase_code: ObservedValue[int]
    remaining_minutes: ObservedValue[int]
    elapsed_minutes: ObservedValue[int]
    scheduled_start_minutes_of_day: ObservedValue[int]
    temperature_c: ObservedValue[int | float]
    spin_speed_rpm: ObservedValue[int | float]
    drying_step_code: ObservedValue[int]
    time: ObservationTime
    quality: Quality
