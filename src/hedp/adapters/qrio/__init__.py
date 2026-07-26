"""Qrio read-only contracts and privacy-safe normalizers."""

from .collector import QrioReadOnlyCollector
from .configuration import QrioConfiguration
from .models import (
    BatteryState,
    LockAction,
    LockEvent,
    LockEventBatch,
    LockHealth,
    LockHealthBatch,
    LockPosition,
    LockStatus,
)
from .normalizer import normalize_health, normalize_history, normalize_status
from .reader import QrioReader, QrioReadPort
from .transport import QrioHttpsReadTransport, QrioTransportError

__all__ = [
    "BatteryState",
    "LockAction",
    "LockEvent",
    "LockEventBatch",
    "LockHealth",
    "LockHealthBatch",
    "LockPosition",
    "LockStatus",
    "QrioReadPort",
    "QrioReadOnlyCollector",
    "QrioConfiguration",
    "QrioReader",
    "QrioHttpsReadTransport",
    "QrioTransportError",
    "normalize_health",
    "normalize_history",
    "normalize_status",
]
