"""Bounded, non-persistent read-only probe for one pending E26 registration."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable
from urllib.parse import quote

import requests

from hedp.observations import Quality

from .client import SwitchBotClient
from .secondary_state import (
    SecondaryDeviceKind,
    SecondaryDeviceRegistration,
)


class ProbeDisposition(str, Enum):
    PENDING_REGISTRATION = "pending_registration"
    VISIBLE_UNVERIFIED = "visible_unverified"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ObservedDeviceTypeCount:
    """Anonymous count preserving the exact vendor-returned deviceType."""

    device_type: str
    count: int

    def __post_init__(self) -> None:
        if not isinstance(self.device_type, str) or not self.device_type.strip():
            raise ValueError("device_type must be a non-empty string")
        if not isinstance(self.count, int) or isinstance(self.count, bool):
            raise TypeError("count must be an integer")
        if self.count < 1:
            raise ValueError("count must be positive")


@dataclass(frozen=True)
class SwitchBotProbeResult:
    target_alias: str
    kind: SecondaryDeviceKind
    disposition: ProbeDisposition
    device_type: str | None
    status_visible: bool
    status_fields: tuple[str, ...]
    quality: Quality
    acquired_at: datetime
    reason: str
    candidate_device_types: tuple[ObservedDeviceTypeCount, ...] = ()
    _vendor_device_id: str | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self.acquired_at.tzinfo is None or self.acquired_at.utcoffset() is None:
            raise ValueError("acquired_at must be timezone-aware")

    def safe_summary(self) -> dict[str, object]:
        """Exclude identifier, name, hub, values, and raw response content."""

        return {
            "target_alias": self.target_alias,
            "device_type": self.device_type,
            "status_fields": list(self.status_fields),
            "quality": self.quality.value,
            "observed_at": self.acquired_at.isoformat(),
            "persisted": False,
        }


class BoundedSwitchBotReadTransport:
    """Perform at most one list GET and a bounded number of status GETs."""

    BASE_URL = "https://api.switch-bot.com/v1.1"

    def __init__(
        self,
        token: str,
        secret: str,
        *,
        timeout_seconds: float = 5,
        response_byte_cap: int = 128 * 1024,
        maximum_status_requests: int = 1,
        wall_clock_deadline_seconds: float = 12,
        request_get: Callable[..., requests.Response] = requests.get,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0 < timeout_seconds <= 10:
            raise ValueError("probe timeout must be greater than 0 and at most 10")
        if not 1024 <= response_byte_cap <= 1024 * 1024:
            raise ValueError("response byte cap must be between 1 KiB and 1 MiB")
        if not 0 <= maximum_status_requests <= 4:
            raise ValueError("maximum_status_requests must be between 0 and 4")
        if not 0 < wall_clock_deadline_seconds <= 20:
            raise ValueError(
                "wall-clock deadline must be greater than 0 and at most 20"
            )
        self._signer = SwitchBotClient(
            token,
            secret,
            timeout_seconds=timeout_seconds,
            max_attempts=1,
        )
        self._timeout_seconds = timeout_seconds
        self._response_byte_cap = response_byte_cap
        self._maximum_status_requests = maximum_status_requests
        self._wall_clock_deadline_seconds = wall_clock_deadline_seconds
        self._request_get = request_get
        self._monotonic = monotonic
        self._started_at: float | None = None
        self._list_requests = 0
        self._status_requests = 0

    def list_devices(self) -> dict[str, Any]:
        if self._list_requests:
            raise PermissionError("device list probe is limited to one request")
        self._list_requests += 1
        return self._get_json("/devices")

    def status(self, vendor_device_id: str) -> dict[str, Any]:
        if self._status_requests >= self._maximum_status_requests:
            raise PermissionError("status probe request limit reached")
        if not isinstance(vendor_device_id, str) or not vendor_device_id:
            raise ValueError("vendor_device_id must be a non-empty string")
        self._status_requests += 1
        encoded = quote(vendor_device_id, safe="")
        return self._get_json(f"/devices/{encoded}/status")

    @property
    def request_counts(self) -> tuple[int, int]:
        return self._list_requests, self._status_requests

    def _get_json(self, path: str) -> dict[str, Any]:
        timeout = min(self._timeout_seconds, self._remaining_seconds())
        response = self._request_get(
            f"{self.BASE_URL}{path}",
            headers=self._signer.authentication_headers(),
            timeout=timeout,
            stream=True,
        )
        response.raise_for_status()
        declared = response.headers.get("Content-Length")
        if declared is not None:
            try:
                declared_size = int(declared)
            except ValueError as error:
                raise ValueError("probe response has an invalid Content-Length") from error
            if declared_size > self._response_byte_cap:
                raise ValueError("probe response exceeds the byte cap")
        chunks = bytearray()
        for chunk in response.iter_content(chunk_size=4096):
            self._remaining_seconds()
            if not chunk:
                continue
            chunks.extend(chunk)
            if len(chunks) > self._response_byte_cap:
                raise ValueError("probe response exceeds the byte cap")
        self._remaining_seconds()
        try:
            value = json.loads(bytes(chunks))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("probe response is not valid JSON") from error
        if not isinstance(value, dict):
            raise ValueError("probe response must be a JSON object")
        return value

    def _remaining_seconds(self) -> float:
        now = self._monotonic()
        if self._started_at is None:
            self._started_at = now
        remaining = self._wall_clock_deadline_seconds - (now - self._started_at)
        if remaining <= 0:
            raise TimeoutError("probe wall-clock deadline exceeded")
        return remaining


class PendingE26Probe:
    """Check anonymous visibility without persisting or exposing household data."""

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

    def run(
        self,
        registration: SecondaryDeviceRegistration,
        *,
        known_registrations: Iterable[SecondaryDeviceRegistration] = (),
        permit_unique_difference_link: bool = False,
    ) -> SwitchBotProbeResult:
        if registration.kind is not SecondaryDeviceKind.E26_SMART_BULB:
            raise ValueError("pending E26 probe accepts only the E26 light kind")

        listing = self._transport.list_devices()
        body = listing.get("body")
        devices = body.get("deviceList") if isinstance(body, dict) else None
        if listing.get("statusCode") != 100 or not isinstance(devices, list):
            return self._blocked(registration, "device_list_shape_invalid")
        if len(devices) > self._maximum_devices:
            return self._blocked(registration, "device_list_limit_exceeded")
        parsed = self._parse_devices(devices)
        if parsed is None:
            return self._blocked(registration, "device_list_entry_invalid")
        if len({item[0] for item in parsed}) != len(parsed):
            return self._blocked(registration, "device_list_identifier_duplicate")

        known_ids = {
            item.vendor_device_id
            for item in known_registrations
            if item.vendor_device_id is not None
        }
        if registration.vendor_device_id is not None:
            known_ids.add(registration.vendor_device_id)
        candidates = tuple(item for item in parsed if item[0] not in known_ids)
        candidate_types = self._count_device_types(candidates)

        matched = next(
            (
                item
                for item in parsed
                if item[0] == registration.vendor_device_id
            ),
            None,
        )
        if matched is None and registration.vendor_device_id is not None:
            return self._pending(
                registration,
                "registered_target_not_visible_yet",
                candidate_types,
            )
        if matched is None:
            if not candidates:
                return self._pending(
                    registration,
                    "registration_not_visible_yet",
                    (),
                )
            if len(candidates) != 1 or not permit_unique_difference_link:
                return self._pending(
                    registration,
                    "new_device_candidates_ambiguous"
                    if len(candidates) != 1
                    else "unique_candidate_link_not_permitted",
                    candidate_types,
                )
            matched = candidates[0]
            link_reason = "unique_new_device_candidate_requires_manual_confirmation"
        else:
            link_reason = "manual_profile_confirmation_required"

        vendor_device_id, device_type = matched
        status = self._transport.status(vendor_device_id)
        status_body = status.get("body")
        if status.get("statusCode") != 100 or not isinstance(status_body, dict):
            return SwitchBotProbeResult(
                registration.target_alias,
                registration.kind,
                ProbeDisposition.VISIBLE_UNVERIFIED,
                device_type.strip(),
                False,
                (),
                Quality.UNKNOWN,
                self._acquired_at(),
                "status_not_visible",
                candidate_types,
                vendor_device_id,
            )
        field_names = tuple(sorted(str(name) for name in status_body))
        if len(field_names) > self._maximum_status_fields:
            return self._blocked(registration, "status_field_limit_exceeded")
        return SwitchBotProbeResult(
            registration.target_alias,
            registration.kind,
            ProbeDisposition.VISIBLE_UNVERIFIED,
            device_type.strip(),
            True,
            field_names,
            Quality.GOOD,
            self._acquired_at(),
            link_reason,
            candidate_types,
            vendor_device_id,
        )

    @staticmethod
    def _parse_devices(
        devices: list[Any],
    ) -> tuple[tuple[str, str], ...] | None:
        parsed = []
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
        candidates: tuple[tuple[str, str], ...],
    ) -> tuple[ObservedDeviceTypeCount, ...]:
        counts: dict[str, int] = {}
        for _, device_type in candidates:
            counts[device_type] = counts.get(device_type, 0) + 1
        return tuple(
            ObservedDeviceTypeCount(device_type, count)
            for device_type, count in sorted(counts.items())
        )

    def _pending(
        self,
        registration: SecondaryDeviceRegistration,
        reason: str,
        candidate_device_types: tuple[ObservedDeviceTypeCount, ...],
    ) -> SwitchBotProbeResult:
        return SwitchBotProbeResult(
            registration.target_alias,
            registration.kind,
            ProbeDisposition.PENDING_REGISTRATION,
            None,
            False,
            (),
            Quality.UNKNOWN,
            self._acquired_at(),
            reason,
            candidate_device_types,
            registration.vendor_device_id,
        )

    def _blocked(
        self,
        registration: SecondaryDeviceRegistration,
        reason: str,
    ) -> SwitchBotProbeResult:
        return SwitchBotProbeResult(
            registration.target_alias,
            registration.kind,
            ProbeDisposition.BLOCKED,
            None,
            False,
            (),
            Quality.INVALID,
            self._acquired_at(),
            reason,
            (),
            registration.vendor_device_id,
        )

    def _acquired_at(self) -> datetime:
        value = self._now()
        if not isinstance(value, datetime):
            raise TypeError("probe clock must return datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("probe clock must return a timezone-aware datetime")
        return value
