"""Read-only camera evidence adapter for outdoor light observation."""

from .acquisition_policy import (
    EnergyAwareSnapshotPolicy,
    EnergyEvidence,
    SnapshotAction,
    SnapshotDecision,
    decide_snapshot_acquisition,
)
from .analysis import analyze_sunlight
from .capabilities import EufyWeatherCapabilities
from .collector import (
    EnergyGatedCollectionResult,
    EufyWeatherCollector,
    collect_if_energy_allows,
)
from .configuration import (
    EufyWeatherConfiguration,
    eufy_weather_configuration_from_mapping,
    load_eufy_weather_configuration,
)
from .errors import (
    SnapshotBackendUnavailable,
    SnapshotError,
    SnapshotTimeout,
    SnapshotUnavailable,
)
from .models import (
    NormalizedRoi,
    RgbFrame,
    SunlightCalibration,
    SunlightObservation,
    SunlightState,
)
from .opencv_reader import OpenCvSnapshotReader
from .qualification import qualification_report
from .reader import SnapshotReader

__all__ = [
    "EufyWeatherCapabilities",
    "EufyWeatherConfiguration",
    "EufyWeatherCollector",
    "EnergyGatedCollectionResult",
    "EnergyAwareSnapshotPolicy",
    "EnergyEvidence",
    "NormalizedRoi",
    "OpenCvSnapshotReader",
    "RgbFrame",
    "SnapshotBackendUnavailable",
    "SnapshotError",
    "SnapshotAction",
    "SnapshotDecision",
    "SnapshotReader",
    "SnapshotTimeout",
    "SnapshotUnavailable",
    "SunlightCalibration",
    "SunlightObservation",
    "SunlightState",
    "analyze_sunlight",
    "collect_if_energy_allows",
    "decide_snapshot_acquisition",
    "eufy_weather_configuration_from_mapping",
    "load_eufy_weather_configuration",
    "qualification_report",
]
