"""Explicit support boundaries for non-device SwitchBot concepts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SwitchBotFeature(str, Enum):
    SCHEDULES = "schedules"
    REPORTS = "reports"
    ROOMS = "rooms"
    REMOTE_CONTROL = "remote_control"


class FeatureDisposition(str, Enum):
    LOCAL_HESTIA = "local_hestia"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class FeatureSupport:
    feature: SwitchBotFeature
    disposition: FeatureDisposition
    reason: str


_SUPPORT = {
    SwitchBotFeature.SCHEDULES: FeatureSupport(
        SwitchBotFeature.SCHEDULES,
        FeatureDisposition.LOCAL_HESTIA,
        "Hestia scheduling metadata only; no SwitchBot schedule endpoint",
    ),
    SwitchBotFeature.REPORTS: FeatureSupport(
        SwitchBotFeature.REPORTS,
        FeatureDisposition.LOCAL_HESTIA,
        "derived from locally collected observations",
    ),
    SwitchBotFeature.ROOMS: FeatureSupport(
        SwitchBotFeature.ROOMS,
        FeatureDisposition.LOCAL_HESTIA,
        "local household aliases and history only",
    ),
    SwitchBotFeature.REMOTE_CONTROL: FeatureSupport(
        SwitchBotFeature.REMOTE_CONTROL,
        FeatureDisposition.UNSUPPORTED,
        "no remote-driving command is admitted by this adapter",
    ),
}


def feature_support(feature: SwitchBotFeature) -> FeatureSupport:
    return _SUPPORT[feature]
