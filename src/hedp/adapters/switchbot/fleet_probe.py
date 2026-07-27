"""Bounded, non-persistent read-only probe for second-stage SwitchBot devices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from hedp.observations import Quality

from .probe import (
    BoundedSwitchBotReadTransport,
    ObservedDeviceTypeCount,
    ProbeDisposition,
    SwitchBotProbeResult,
)
from .secondary_state import SecondaryDeviceKind


_TARGETS: tuple[tuple[str, SecondaryDeviceKind, str], ...] = (
    ("motion-sensor", SecondaryDeviceKind.MOTION_SENSOR, "Motion Sensor"),
    (
        "presence-sensor-pro",
        SecondaryDeviceKind.PRESENCE_SENSOR_PRO,
        "Presence Sensor Pro",
    ),
    ("e26-smart-bulb", SecondaryDeviceKind.E26_SMART_BULB, "Color Bulb"),
    ("strip-light-3", SecondaryDeviceKind.STRIP_LIGHT_3, "Strip Light 3"),
)
_ADMITTED_DEVICE_TYPES = frozenset(item[2] for item in _TARGETS)


@dataclass(frozen=True)
class SecondaryFleetProbeReport:
    """Anonymous evidence from one bounded fleet inspection."""

    results: tuple[SwitchBotProbeResult, ...]
    observed_device_types: tuple[ObservedDeviceTypeCount, ...]

    def safe_summary(self) -> dict[str, object]:
        return {
            "devices": [result.safe_summary() for result in self.results],
            "observed_device_types": [
                {"device_type": item.device_type, "count": item.count}
                for item in self.observed_device_types
            ],
            "persisted": False,
        }


class SecondaryFleetProbe:
    """Inspect four admitted families without persisting or returning values."""

    def __init__(
        self,
        transport: BoundedSwitchBotReadTransport,
        *,
        maximum_devices: int = 256,
        maximum_status_fields: int = 64,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if not 1 <= maximum_devices <= 512:
            raise ValueError("maximum_devices must be between 1 and 512")
        if not 1 <= maximum_status_fields <= 128:
            raise ValueError("maximum_status_fields must be between 1 and 128")
        self._transport = transport
        self._maximum_devices = maximum_devices
        self._maximum_status_fields = maximum_status_fields
        self._now = now

    def run(self) -> SecondaryFleetProbeReport:
        listing = self._transport.list_devices()
        body = listing.get("body")
        devices = body.get("deviceList") if isinstance(body, dict) else None
        if listing.get("statusCode") != 100 or not isinstance(devices, list):
            return self._blocked_report("device_list_shape_invalid")
        if len(devices) > self._maximum_devices:
            return self._blocked_report("device_list_limit_exceeded")
        parsed = self._parse_devices(devices)
        if parsed is None:
            return self._blocked_report("device_list_entry_invalid")
        if len({item[0] for item in parsed}) != len(parsed):
            return self._blocked_report("device_list_identifier_duplicate")

        counts = self._count_device_types(parsed)
        results = tuple(
            self._probe_target(alias, kind, expected_type, parsed)
            for alias, kind, expected_type in _TARGETS
        )
        return SecondaryFleetProbeReport(results, counts)

    def _probe_target(
        self,
        alias: str,
        kind: SecondaryDeviceKind,
        expected_type: str,
        devices: tuple[tuple[str, str], ...],
    ) -> SwitchBotProbeResult:
        matches = tuple(item for item in devices if item[1] == expected_type)
        acquired_at = self._acquired_at()
        if not matches:
            return SwitchBotProbeResult(
                alias,
                kind,
                ProbeDisposition.PENDING_REGISTRATION,
                None,
                False,
                (),
                Quality.UNKNOWN,
                acquired_at,
                "exact_device_type_not_visible",
            )
        if len(matches) != 1:
            return SwitchBotProbeResult(
                alias,
                kind,
                ProbeDisposition.PENDING_REGISTRATION,
                expected_type,
                False,
                (),
                Quality.UNKNOWN,
                acquired_at,
                "exact_device_type_ambiguous",
            )

        vendor_device_id, observed_type = matches[0]
        status = self._transport.status(vendor_device_id)
        status_body = status.get("body")
        if status.get("statusCode") != 100 or not isinstance(status_body, dict):
            return SwitchBotProbeResult(
                alias,
                kind,
                ProbeDisposition.VISIBLE_UNVERIFIED,
                observed_type,
                False,
                (),
                Quality.UNKNOWN,
                acquired_at,
                "status_not_visible",
            )
        fields = tuple(sorted(str(name) for name in status_body))
        if len(fields) > self._maximum_status_fields:
            return SwitchBotProbeResult(
                alias,
                kind,
                ProbeDisposition.BLOCKED,
                observed_type,
                False,
                (),
                Quality.INVALID,
                acquired_at,
                "status_field_limit_exceeded",
            )
        return SwitchBotProbeResult(
            alias,
            kind,
            ProbeDisposition.VISIBLE_UNVERIFIED,
            observed_type,
            True,
            fields,
            Quality.GOOD,
            acquired_at,
            "exact_device_type_observed_status_visible",
        )

    @staticmethod
    def _parse_devices(
        devices: list[Any],
    ) -> tuple[tuple[str, str], ...] | None:
        parsed: list[tuple[str, str]] = []
        for item in devices:
            if not isinstance(item, dict):
                return None
            vendor_device_id = item.get("deviceId")
            device_type = item.get("deviceType")
            if (
                not isinstance(vendor_device_id, str)
                or not vendor_device_id
                or not isinstance(device_type, str)
                or not device_type.strip()
            ):
                return None
            parsed.append((vendor_device_id, device_type.strip()))
        return tuple(parsed)

    @staticmethod
    def _count_device_types(
        devices: tuple[tuple[str, str], ...],
    ) -> tuple[ObservedDeviceTypeCount, ...]:
        counts: dict[str, int] = {}
        for _, device_type in devices:
            if device_type in _ADMITTED_DEVICE_TYPES:
                counts[device_type] = counts.get(device_type, 0) + 1
        return tuple(
            ObservedDeviceTypeCount(device_type, count)
            for device_type, count in sorted(counts.items())
        )

    def _blocked_report(self, reason: str) -> SecondaryFleetProbeReport:
        acquired_at = self._acquired_at()
        results = tuple(
            SwitchBotProbeResult(
                alias,
                kind,
                ProbeDisposition.BLOCKED,
                None,
                False,
                (),
                Quality.INVALID,
                acquired_at,
                reason,
            )
            for alias, kind, _ in _TARGETS
        )
        return SecondaryFleetProbeReport(results, ())

    def _acquired_at(self) -> datetime:
        value = self._now()
        if not isinstance(value, datetime):
            raise TypeError("probe clock must return datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("probe clock must return a timezone-aware datetime")
        return value
