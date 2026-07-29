"""Explicit capability boundary for the pre-device Eufy weather adapter."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EufyWeatherCapabilities:
    """Facts about the adapter, not claims about an unqualified camera."""

    read_only: bool = True
    snapshot_analysis: bool = True
    retains_images: bool = False
    relative_illumination: bool = True
    shadow_contrast: bool = True
    absolute_lux: bool = False
    camera_control: bool = False
    continuous_stream_required: bool = False
    e42_rtsp_wake_live_confirmed: bool = False
