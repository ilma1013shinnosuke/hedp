"""Read-only frame acquisition boundary."""

from __future__ import annotations

from typing import Protocol

from .models import RgbFrame


class SnapshotReader(Protocol):
    """Read exactly one frame without exposing camera-control methods."""

    def read_snapshot(self, *, timeout_seconds: float) -> RgbFrame: ...
