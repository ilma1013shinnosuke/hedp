"""Safe, transport-independent models for Smart LEDZ read responses."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Quality(str, Enum):
    """Whether a response is safe to use as an observed fact."""

    GOOD = "good"
    MISSING = "missing"
    INVALID = "invalid"
    UNKNOWN = "unknown"


class ResourceKind(str, Enum):
    GROUP = "group"
    SCENE = "scene"
    SCHEDULE = "schedule"
    DEVICE = "device"
    SENSOR = "sensor"


@dataclass(frozen=True)
class ResourceResponse:
    """The safe boundary around one already-acquired resource response.

    Only ``ErrorCode=0`` is observed as an accepted Smart LEDZ response.  The
    nested schemas have not yet been confirmed, so this model deliberately
    retains their *field names*, not their values.  This lets callers detect a
    schema change without treating unknown values, names, identifiers, or
    configuration as normalised state.
    """

    resource: ResourceKind
    quality: Quality
    reason: str | None = None
    error_code: int | None = None
    unknown_fields: tuple[str, ...] = ()
    redacted_field_count: int = 0


@dataclass(frozen=True)
class SmartLedzReading:
    """A batch of independently acquired, read-only Smart LEDZ responses."""

    groups: ResourceResponse
    scenes: ResourceResponse
    schedules: ResourceResponse
    devices: ResourceResponse
    sensors: ResourceResponse
    observed_at: str
    received_at: str
