"""Offline composition of already-acquired Smart LEDZ read responses."""

from __future__ import annotations

from dataclasses import dataclass

from .models import SmartLedzReading
from .normalizer import (
    normalize_device_response,
    normalize_group_response,
    normalize_scene_response,
    normalize_schedule_response,
    normalize_sensor_response,
)


@dataclass(frozen=True)
class ReadBatch:
    """Read-only responses acquired by a separate transport boundary.

    This class intentionally accepts decoded objects only.  It does not know
    about TCP sockets, frames, request IDs, authentication, retries, or any
    device operation.
    """

    group_response: object
    scene_response: object
    schedule_response: object
    device_response: object
    sensor_response: object
    observed_at: str
    received_at: str


def normalize_read_batch(batch: ReadBatch) -> SmartLedzReading:
    """Normalise a read batch without communication or side effects."""

    return SmartLedzReading(
        groups=normalize_group_response(batch.group_response),
        scenes=normalize_scene_response(batch.scene_response),
        schedules=normalize_schedule_response(batch.schedule_response),
        devices=normalize_device_response(batch.device_response),
        sensors=normalize_sensor_response(batch.sensor_response),
        observed_at=batch.observed_at,
        received_at=batch.received_at,
    )
