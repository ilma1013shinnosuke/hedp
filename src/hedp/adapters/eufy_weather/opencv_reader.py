"""Optional OpenCV snapshot reader.

OpenCV is intentionally loaded lazily.  The HESTIA core and its tests do not
depend on OpenCV; a runtime that owns a camera can install it separately.
"""

from __future__ import annotations

from datetime import datetime, timezone
from importlib import import_module
from typing import Any, Callable

from .errors import (
    SnapshotBackendUnavailable,
    SnapshotTimeout,
    SnapshotUnavailable,
)
from .models import RgbFrame


class OpenCvSnapshotReader:
    """Read and downsample one RTSP frame; never controls the camera."""

    def __init__(
        self,
        stream_url: str,
        *,
        analysis_width: int = 320,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        cv2_loader: Callable[[], Any] | None = None,
    ) -> None:
        if not isinstance(stream_url, str) or not stream_url:
            raise ValueError("stream_url must not be empty")
        if not 64 <= analysis_width <= 640:
            raise ValueError("analysis_width must be between 64 and 640")
        self._stream_url = stream_url
        self._analysis_width = analysis_width
        self._clock = clock
        self._cv2_loader = cv2_loader or _load_cv2

    def read_snapshot(self, *, timeout_seconds: float) -> RgbFrame:
        if not 0 < timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be greater than 0 and at most 30")
        cv2 = self._cv2_loader()
        timeout_millis = int(timeout_seconds * 1_000)
        capture = cv2.VideoCapture()
        try:
            _set_timeout(capture, cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", timeout_millis)
            _set_timeout(capture, cv2, "CAP_PROP_READ_TIMEOUT_MSEC", timeout_millis)
            if not capture.open(self._stream_url):
                raise SnapshotUnavailable()
            ok, frame = capture.read()
            if not ok or frame is None:
                raise SnapshotTimeout()
            height, width = frame.shape[:2]
            if width <= 0 or height <= 0:
                raise SnapshotUnavailable()
            if width > self._analysis_width:
                output_height = max(1, round(height * self._analysis_width / width))
                frame = cv2.resize(
                    frame,
                    (self._analysis_width, output_height),
                    interpolation=cv2.INTER_AREA,
                )
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            captured_at = self._clock()
            if captured_at.tzinfo is None or captured_at.utcoffset() is None:
                raise ValueError("clock must return a timezone-aware datetime")
            return RgbFrame(
                pixels=tuple(
                    tuple(
                        (int(pixel[0]), int(pixel[1]), int(pixel[2]))
                        for pixel in row
                    )
                    for row in rgb
                ),
                captured_at=captured_at.isoformat(),
            )
        finally:
            capture.release()


def _load_cv2() -> Any:
    try:
        return import_module("cv2")
    except ImportError as exc:
        raise SnapshotBackendUnavailable() from exc


def _set_timeout(capture: Any, cv2: Any, name: str, value: int) -> None:
    property_id = getattr(cv2, name, None)
    if property_id is not None:
        capture.set(property_id, value)
