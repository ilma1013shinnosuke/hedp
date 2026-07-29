"""Pure-Python analysis of relative illumination and visible shadow evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from hedp.observations import ObservationTime, ObservedValue, Quality

from .models import (
    NormalizedRoi,
    RgbFrame,
    SunlightCalibration,
    SunlightObservation,
    SunlightState,
)


def analyze_sunlight(
    frame: RgbFrame,
    *,
    target_ref: str,
    sky_roi: NormalizedRoi,
    shadow_roi: NormalizedRoi,
    calibration: SunlightCalibration | None = None,
    attempt_count: int = 1,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> SunlightObservation:
    """Turn a snapshot into compact evidence without retaining the image."""

    received_at = clock()
    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")

    sky = _luminance_values(frame, sky_roi)
    shadow_surface = _luminance_values(frame, shadow_roi)
    time = ObservationTime(frame.captured_at, received_at.isoformat())
    # Four pixels are too easily dominated by compression noise or one hot
    # pixel. Eight is still small because the input is already downsampled.
    if len(sky) < 8 or len(shadow_surface) < 8:
        return _invalid_observation(
            target_ref=target_ref,
            time=time,
            attempt_count=attempt_count,
            reason="roi_too_small",
        )

    illumination = sum(sky) / len(sky)
    shadow_contrast = _percentile(shadow_surface, 0.90) - _percentile(
        shadow_surface, 0.10
    )
    all_values = sky + shadow_surface
    clipped_fraction = sum(
        value <= 1 / 255 or value >= 254 / 255 for value in all_values
    ) / len(all_values)

    state = _classify(
        illumination=illumination,
        shadow_contrast=shadow_contrast,
        calibration=calibration,
    )
    return SunlightObservation(
        target_ref=target_ref,
        state=state,
        illumination_index=ObservedValue(
            value=round(illumination, 6),
            quality=Quality.GOOD,
        ),
        shadow_contrast=ObservedValue(
            value=round(shadow_contrast, 6),
            quality=Quality.GOOD,
        ),
        clipped_fraction=ObservedValue(
            value=round(clipped_fraction, 6),
            quality=Quality.GOOD,
        ),
        time=time,
        quality=Quality.GOOD,
        attempt_count=attempt_count,
    )


def unavailable_observation(
    *,
    target_ref: str,
    observed_at: str,
    received_at: str,
    attempt_count: int,
    reason: str,
) -> SunlightObservation:
    time = ObservationTime(observed_at, received_at)
    missing = ObservedValue[float](
        value=None,
        quality=Quality.MISSING,
        reason=reason,
    )
    return SunlightObservation(
        target_ref=target_ref,
        state=ObservedValue(
            value=None,
            quality=Quality.MISSING,
            reason=reason,
        ),
        illumination_index=missing,
        shadow_contrast=missing,
        clipped_fraction=missing,
        time=time,
        quality=Quality.MISSING,
        attempt_count=attempt_count,
    )


def _invalid_observation(
    *,
    target_ref: str,
    time: ObservationTime,
    attempt_count: int,
    reason: str,
) -> SunlightObservation:
    invalid = ObservedValue[float](
        value=None,
        quality=Quality.INVALID,
        reason=reason,
    )
    return SunlightObservation(
        target_ref=target_ref,
        state=ObservedValue(
            value=None,
            quality=Quality.INVALID,
            reason=reason,
        ),
        illumination_index=invalid,
        shadow_contrast=invalid,
        clipped_fraction=invalid,
        time=time,
        quality=Quality.INVALID,
        attempt_count=attempt_count,
    )


def _classify(
    *,
    illumination: float,
    shadow_contrast: float,
    calibration: SunlightCalibration | None,
) -> ObservedValue[SunlightState]:
    if calibration is None:
        return ObservedValue(
            value=None,
            quality=Quality.UNKNOWN,
            reason="site_calibration_required",
        )
    if illumination <= calibration.low_light_max_illumination:
        state = SunlightState.LOW_LIGHT
    elif (
        illumination >= calibration.direct_sun_min_illumination
        and shadow_contrast >= calibration.direct_sun_min_shadow_contrast
    ):
        state = SunlightState.DIRECT_SUN
    else:
        state = SunlightState.DIFFUSE_LIGHT
    return ObservedValue(value=state, quality=Quality.ESTIMATED)


def _luminance_values(frame: RgbFrame, roi: NormalizedRoi) -> list[float]:
    left, top, right, bottom = roi.pixel_bounds(frame.width, frame.height)
    return [
        _luminance(frame.pixels[y][x])
        for y in range(top, bottom)
        for x in range(left, right)
    ]


def _luminance(pixel: tuple[int, int, int]) -> float:
    red, green, blue = pixel
    return (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return ordered[index]
