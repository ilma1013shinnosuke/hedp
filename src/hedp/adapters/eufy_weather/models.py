"""OS-independent models for camera-derived sunlight evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from hedp.observations import ObservationTime, ObservedValue, Quality


RgbPixel = tuple[int, int, int]


class SunlightState(str, Enum):
    """A conservative light state, not a meteorological weather claim."""

    DIRECT_SUN = "direct_sun"
    DIFFUSE_LIGHT = "diffuse_light"
    LOW_LIGHT = "low_light"


@dataclass(frozen=True)
class NormalizedRoi:
    """Region of interest expressed as fractions of the frame dimensions."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        values = (self.x, self.y, self.width, self.height)
        if not all(isinstance(value, (int, float)) for value in values):
            raise TypeError("ROI coordinates must be numbers")
        if self.x < 0 or self.y < 0:
            raise ValueError("ROI origin must not be negative")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("ROI dimensions must be greater than zero")
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("ROI must fit inside the normalized frame")

    def pixel_bounds(self, frame_width: int, frame_height: int) -> tuple[int, int, int, int]:
        left = min(frame_width - 1, int(self.x * frame_width))
        top = min(frame_height - 1, int(self.y * frame_height))
        right = min(frame_width, max(left + 1, int((self.x + self.width) * frame_width)))
        bottom = min(
            frame_height,
            max(top + 1, int((self.y + self.height) * frame_height)),
        )
        return left, top, right, bottom


@dataclass(frozen=True)
class RgbFrame:
    """A deliberately downsampled RGB snapshot.

    Pixel data is excluded from repr so diagnostics cannot accidentally print
    an image of the household.
    """

    pixels: tuple[tuple[RgbPixel, ...], ...] = field(repr=False)
    captured_at: str

    def __post_init__(self) -> None:
        ObservationTime(self.captured_at, self.captured_at)
        if not self.pixels or not self.pixels[0]:
            raise ValueError("frame must contain at least one pixel")
        width = len(self.pixels[0])
        for row in self.pixels:
            if len(row) != width:
                raise ValueError("all frame rows must have the same width")
            for pixel in row:
                if len(pixel) != 3:
                    raise ValueError("RGB pixels must have exactly three channels")
                if any(
                    not isinstance(channel, int) or not 0 <= channel <= 255
                    for channel in pixel
                ):
                    raise ValueError("RGB channels must be integers from 0 to 255")

    @property
    def width(self) -> int:
        return len(self.pixels[0])

    @property
    def height(self) -> int:
        return len(self.pixels)


@dataclass(frozen=True)
class SunlightCalibration:
    """Site-specific thresholds established from real observations."""

    direct_sun_min_illumination: float
    direct_sun_min_shadow_contrast: float
    low_light_max_illumination: float

    def __post_init__(self) -> None:
        values = (
            self.direct_sun_min_illumination,
            self.direct_sun_min_shadow_contrast,
            self.low_light_max_illumination,
        )
        if not all(0 <= value <= 1 for value in values):
            raise ValueError("calibration thresholds must be between 0 and 1")
        if self.low_light_max_illumination >= self.direct_sun_min_illumination:
            raise ValueError(
                "low-light threshold must be below direct-sun illumination threshold"
            )


@dataclass(frozen=True)
class SunlightObservation:
    """Privacy-minimized evidence derived from one frame."""

    target_ref: str = field(repr=False)
    state: ObservedValue[SunlightState]
    illumination_index: ObservedValue[float]
    shadow_contrast: ObservedValue[float]
    clipped_fraction: ObservedValue[float]
    time: ObservationTime
    quality: Quality
    attempt_count: int

    def __post_init__(self) -> None:
        if not self.target_ref:
            raise ValueError("target_ref must not be empty")
        if not 1 <= self.attempt_count <= 2:
            raise ValueError("attempt_count must be between 1 and 2")
