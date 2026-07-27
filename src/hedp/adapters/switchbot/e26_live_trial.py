"""One-off, bounded E26 brightness trial with mandatory compensation.

This module is deliberately narrower than the production operation adapter.
It admits exactly one Color Bulb, changes brightness by five percentage
points, verifies the change, restores the original value, and verifies the
restoration.  It never changes power, color, color temperature, or scenes.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import requests

from hedp.operations.execution import (
    Authorization,
    ExecutionCapability,
    ExecutionCoordinator,
    ExecutionOutcome,
)
from hedp.operations.shadow_execution import EvidenceQuality, Intent, StateEvidence

from .client import SwitchBotClient


TARGET_ALIAS = "e26-smart-bulb"
EXPECTED_DEVICE_TYPE = "Color Bulb"
CONTROL_OWNER = "switchbot-openapi"
LIGHT_EXECUTION_CAPABILITY = "switchbot-light-state-set"
BRIGHTNESS_STEP = 5
MINIMUM_TRIAL_BRIGHTNESS = 6
MAXIMUM_TRIAL_BRIGHTNESS = 95


@dataclass(frozen=True)
class _TrialBrightnessState:
    """Private gate value; production light contracts remain in operation.py."""

    brightness: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.brightness, bool)
            or not isinstance(self.brightness, int)
            or not 1 <= self.brightness <= 100
        ):
            raise ValueError("brightness must be from 1 to 100")


@dataclass(frozen=True)
class E26TrialResult:
    reason: str
    reader_qualified: bool
    writer_qualified: bool
    gate_qualified: bool
    initial_state_eligible: bool
    change_attempted: bool
    change_confirmed: bool
    restore_attempted: bool
    restore_confirmed: bool
    final_state_matches: bool
    list_requests: int
    status_requests: int
    command_requests: int

    def safe_summary(self) -> dict[str, object]:
        """Return no device identifier, secret, raw value, or target value."""

        return {
            "target_alias": TARGET_ALIAS,
            "reason": self.reason,
            "reader_qualified": self.reader_qualified,
            "writer_qualified": self.writer_qualified,
            "gate_qualified": self.gate_qualified,
            "initial_state_eligible": self.initial_state_eligible,
            "change_attempted": self.change_attempted,
            "change_confirmed": self.change_confirmed,
            "restore_attempted": self.restore_attempted,
            "restore_confirmed": self.restore_confirmed,
            "final_state_matches": self.final_state_matches,
            "list_requests": self.list_requests,
            "status_requests": self.status_requests,
            "command_requests": self.command_requests,
            "stopped_after_e26": True,
            "persisted": False,
        }


class BoundedE26TrialTransport:
    """Two commands maximum: one trial command and one compensation command."""

    BASE_URL = "https://api.switch-bot.com/v1.1"

    def __init__(
        self,
        token: str,
        secret: str,
        *,
        timeout_seconds: float = 5,
        response_byte_cap: int = 128 * 1024,
        maximum_status_requests: int = 7,
        wall_clock_deadline_seconds: float = 45,
        request_get: Callable[..., requests.Response] = requests.get,
        request_post: Callable[..., requests.Response] = requests.post,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0 < timeout_seconds <= 10:
            raise ValueError("timeout must be greater than 0 and at most 10 seconds")
        if not 1024 <= response_byte_cap <= 1024 * 1024:
            raise ValueError("response byte cap must be between 1 KiB and 1 MiB")
        if not 1 <= maximum_status_requests <= 7:
            raise ValueError("maximum_status_requests must be between 1 and 7")
        if not 0 < wall_clock_deadline_seconds <= 60:
            raise ValueError("wall-clock deadline must be at most 60 seconds")
        self._signer = SwitchBotClient(token, secret, timeout_seconds=timeout_seconds)
        self._timeout_seconds = timeout_seconds
        self._response_byte_cap = response_byte_cap
        self._maximum_status_requests = maximum_status_requests
        self._wall_clock_deadline_seconds = wall_clock_deadline_seconds
        self._request_get = request_get
        self._request_post = request_post
        self._monotonic = monotonic
        self._started_at: float | None = None
        self._list_requests = 0
        self._status_requests = 0
        self._command_requests = 0

    @property
    def request_counts(self) -> tuple[int, int, int]:
        return (
            self._list_requests,
            self._status_requests,
            self._command_requests,
        )

    def list_devices(self) -> dict[str, Any]:
        if self._list_requests:
            raise PermissionError("device list is limited to one request")
        self._list_requests += 1
        return self._request_json("GET", "/devices")

    def status(self, vendor_device_id: str) -> dict[str, Any]:
        if self._status_requests >= self._maximum_status_requests:
            raise PermissionError("status request limit reached")
        if not isinstance(vendor_device_id, str) or not vendor_device_id:
            raise ValueError("vendor device identifier is required")
        self._status_requests += 1
        encoded = quote(vendor_device_id, safe="")
        return self._request_json("GET", f"/devices/{encoded}/status")

    def set_brightness(
        self,
        vendor_device_id: str,
        brightness: int,
    ) -> dict[str, Any]:
        if self._command_requests >= 2:
            raise PermissionError("trial is limited to change and restore commands")
        if (
            not isinstance(brightness, int)
            or isinstance(brightness, bool)
            or not 1 <= brightness <= 100
        ):
            raise ValueError("brightness must be an integer from 1 to 100")
        self._command_requests += 1
        encoded = quote(vendor_device_id, safe="")
        return self._request_json(
            "POST",
            f"/devices/{encoded}/commands",
            payload={
                "command": "setBrightness",
                "parameter": str(brightness),
                "commandType": "command",
            },
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        timeout = min(self._timeout_seconds, self._remaining_seconds())
        request = self._request_get if method == "GET" else self._request_post
        kwargs: dict[str, object] = {
            "headers": self._signer.authentication_headers(),
            "timeout": timeout,
            "stream": True,
        }
        if payload is not None:
            kwargs["json"] = payload
        response = request(f"{self.BASE_URL}{path}", **kwargs)
        response.raise_for_status()
        declared = response.headers.get("Content-Length")
        if declared is not None:
            try:
                declared_size = int(declared)
            except ValueError as error:
                raise ValueError("response has invalid Content-Length") from error
            if declared_size > self._response_byte_cap:
                raise ValueError("response exceeds byte cap")
        content = bytearray()
        for chunk in response.iter_content(chunk_size=4096):
            self._remaining_seconds()
            if not chunk:
                continue
            content.extend(chunk)
            if len(content) > self._response_byte_cap:
                raise ValueError("response exceeds byte cap")
        try:
            value = json.loads(bytes(content))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("response is not valid JSON") from error
        if not isinstance(value, dict):
            raise ValueError("response must be a JSON object")
        return value

    def _remaining_seconds(self) -> float:
        now = self._monotonic()
        if self._started_at is None:
            self._started_at = now
        remaining = self._wall_clock_deadline_seconds - (now - self._started_at)
        if remaining <= 0:
            raise TimeoutError("trial wall-clock deadline exceeded")
        return remaining


class E26BrightnessTrial:
    """Run one explicitly authorized, automatically compensated E26 trial."""

    def __init__(
        self,
        transport: BoundedE26TrialTransport,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        sleeper: Callable[[float], None] = time.sleep,
        readback_delays: tuple[float, ...] = (0.4, 0.8, 1.2),
    ) -> None:
        if not readback_delays or len(readback_delays) > 3:
            raise ValueError("one to three readback delays are required")
        if any(delay < 0 or delay > 2 for delay in readback_delays):
            raise ValueError("readback delays must be between 0 and 2 seconds")
        self._transport = transport
        self._clock = clock
        self._sleeper = sleeper
        self._readback_delays = readback_delays

    def run(self) -> E26TrialResult:
        reader_qualified = False
        writer_qualified = False
        gate_qualified = False
        eligible = False
        change_attempted = False
        change_confirmed = False
        restore_attempted = False
        restore_confirmed = False
        final_matches = False
        reason = "trial_not_started"
        vendor_device_id: str | None = None
        original_brightness: int | None = None

        try:
            listing = self._transport.list_devices()
            vendor_device_id = _unique_e26_identifier(listing)
            if vendor_device_id is None:
                reason = "exact_e26_not_unique"
                return self._result(
                    reason,
                    reader_qualified,
                    writer_qualified,
                    gate_qualified,
                    eligible,
                    change_attempted,
                    change_confirmed,
                    restore_attempted,
                    restore_confirmed,
                    final_matches,
                )

            initial = self._transport.status(vendor_device_id)
            state = _parse_e26_state(initial)
            if state is None:
                reason = "initial_state_invalid"
                return self._result(
                    reason,
                    reader_qualified,
                    writer_qualified,
                    gate_qualified,
                    eligible,
                    change_attempted,
                    change_confirmed,
                    restore_attempted,
                    restore_confirmed,
                    final_matches,
                )
            power_on, original_brightness = state
            reader_qualified = True
            writer_qualified = True
            if not power_on:
                reason = "initial_power_off"
                return self._result(
                    reason,
                    reader_qualified,
                    writer_qualified,
                    gate_qualified,
                    eligible,
                    change_attempted,
                    change_confirmed,
                    restore_attempted,
                    restore_confirmed,
                    final_matches,
                )
            if not (
                MINIMUM_TRIAL_BRIGHTNESS
                <= original_brightness
                <= MAXIMUM_TRIAL_BRIGHTNESS
            ):
                reason = "initial_brightness_boundary"
                return self._result(
                    reason,
                    reader_qualified,
                    writer_qualified,
                    gate_qualified,
                    eligible,
                    change_attempted,
                    change_confirmed,
                    restore_attempted,
                    restore_confirmed,
                    final_matches,
                )

            eligible = True
            target = _safe_target(original_brightness)
            checked_at = self._aware_now()
            gate_qualified = _gate_allows(
                original_brightness=original_brightness,
                target_brightness=target,
                evaluated_at=checked_at,
            )
            if not gate_qualified:
                reason = "execution_gate_blocked"
                return self._result(
                    reason,
                    reader_qualified,
                    writer_qualified,
                    gate_qualified,
                    eligible,
                    change_attempted,
                    change_confirmed,
                    restore_attempted,
                    restore_confirmed,
                    final_matches,
                )

            change_attempted = True
            change_response = self._transport.set_brightness(
                vendor_device_id,
                target,
            )
            if not _command_accepted(change_response):
                reason = "change_rejected"
                return self._result(
                    reason,
                    reader_qualified,
                    writer_qualified,
                    gate_qualified,
                    eligible,
                    change_attempted,
                    change_confirmed,
                    restore_attempted,
                    restore_confirmed,
                    final_matches,
                )

            change_confirmed = self._wait_for_brightness(vendor_device_id, target)
            restore_attempted = True
            restore_response = self._transport.set_brightness(
                vendor_device_id,
                original_brightness,
            )
            if not _command_accepted(restore_response):
                reason = "restore_rejected"
                return self._result(
                    reason,
                    reader_qualified,
                    writer_qualified,
                    gate_qualified,
                    eligible,
                    change_attempted,
                    change_confirmed,
                    restore_attempted,
                    restore_confirmed,
                    final_matches,
                )

            restore_confirmed = self._wait_for_brightness(
                vendor_device_id,
                original_brightness,
            )
            final_matches = restore_confirmed
            reason = (
                "changed_and_restored"
                if change_confirmed and restore_confirmed
                else (
                    "change_unconfirmed_restored"
                    if restore_confirmed
                    else "restore_unconfirmed"
                )
            )
        except Exception:
            # If the change may have reached the device, make exactly one
            # best-effort compensation attempt.  Never retry the change.
            if (
                change_attempted
                and not restore_attempted
                and vendor_device_id is not None
                and original_brightness is not None
            ):
                restore_attempted = True
                try:
                    response = self._transport.set_brightness(
                        vendor_device_id,
                        original_brightness,
                    )
                    if _command_accepted(response):
                        restore_confirmed = self._wait_for_brightness(
                            vendor_device_id,
                            original_brightness,
                        )
                        final_matches = restore_confirmed
                except Exception:
                    restore_confirmed = False
                    final_matches = False
            reason = (
                "trial_error_restored"
                if restore_confirmed
                else "trial_error_restore_unconfirmed"
            )
        return self._result(
            reason,
            reader_qualified,
            writer_qualified,
            gate_qualified,
            eligible,
            change_attempted,
            change_confirmed,
            restore_attempted,
            restore_confirmed,
            final_matches,
        )

    def _wait_for_brightness(self, vendor_device_id: str, expected: int) -> bool:
        for delay in self._readback_delays:
            if delay:
                self._sleeper(delay)
            state = _parse_e26_state(self._transport.status(vendor_device_id))
            if state is not None and state[0] and state[1] == expected:
                return True
        return False

    def _result(
        self,
        reason: str,
        reader_qualified: bool,
        writer_qualified: bool,
        gate_qualified: bool,
        eligible: bool,
        change_attempted: bool,
        change_confirmed: bool,
        restore_attempted: bool,
        restore_confirmed: bool,
        final_matches: bool,
    ) -> E26TrialResult:
        list_requests, status_requests, command_requests = (
            self._transport.request_counts
        )
        return E26TrialResult(
            reason,
            reader_qualified,
            writer_qualified,
            gate_qualified,
            eligible,
            change_attempted,
            change_confirmed,
            restore_attempted,
            restore_confirmed,
            final_matches,
            list_requests,
            status_requests,
            command_requests,
        )

    def _aware_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value


def _unique_e26_identifier(listing: dict[str, Any]) -> str | None:
    body = listing.get("body")
    devices = body.get("deviceList") if isinstance(body, dict) else None
    if listing.get("statusCode") != 100 or not isinstance(devices, list):
        return None
    matches: list[str] = []
    for item in devices:
        if not isinstance(item, dict):
            return None
        device_type = item.get("deviceType")
        device_id = item.get("deviceId")
        if device_type == EXPECTED_DEVICE_TYPE:
            if not isinstance(device_id, str) or not device_id:
                return None
            matches.append(device_id)
    return matches[0] if len(matches) == 1 else None


def _parse_e26_state(status: dict[str, Any]) -> tuple[bool, int] | None:
    body = status.get("body")
    if status.get("statusCode") != 100 or not isinstance(body, dict):
        return None
    if body.get("deviceType") != EXPECTED_DEVICE_TYPE:
        return None
    power = body.get("power")
    brightness = body.get("brightness")
    if not isinstance(power, str):
        return None
    normalized_power = power.strip().casefold()
    if normalized_power not in {"on", "off"}:
        return None
    if (
        isinstance(brightness, bool)
        or not isinstance(brightness, int)
        or not 1 <= brightness <= 100
    ):
        return None
    return normalized_power == "on", brightness


def _safe_target(original: int) -> int:
    if not MINIMUM_TRIAL_BRIGHTNESS <= original <= MAXIMUM_TRIAL_BRIGHTNESS:
        raise ValueError("brightness is outside the trial range")
    return original + BRIGHTNESS_STEP if original <= 50 else original - BRIGHTNESS_STEP


def _gate_allows(
    *,
    original_brightness: int,
    target_brightness: int,
    evaluated_at: datetime,
) -> bool:
    maximum_state_age = timedelta(minutes=2)
    desired = _TrialBrightnessState(target_brightness)
    operation_id = f"e26trial-{uuid.uuid4().hex}"
    intent = Intent(
        operation_id=operation_id,
        requested_at=evaluated_at,
        expires_at=evaluated_at + timedelta(minutes=2),
        requester="user",
        reason="approved-e26-five-percent-trial",
        target_alias=TARGET_ALIAS,
        capability=LIGHT_EXECUTION_CAPABILITY,
        desired_state=desired,
        priority=0,
        control_owner=CONTROL_OWNER,
        correlation_id=f"corr-{uuid.uuid4().hex}",
    )
    authorization = Authorization(
        operation_id=operation_id,
        requester="user",
        target_alias=TARGET_ALIAS,
        capability=LIGHT_EXECUTION_CAPABILITY,
        desired_state=desired,
        granted_at=evaluated_at,
        expires_at=evaluated_at + timedelta(minutes=2),
    )
    evidence = StateEvidence(
        target_alias=TARGET_ALIAS,
        capability=LIGHT_EXECUTION_CAPABILITY,
        observed_at=evaluated_at,
        quality=EvidenceQuality.GOOD,
        current_state=_TrialBrightnessState(original_brightness),
    )
    result = ExecutionCoordinator(
        (
            ExecutionCapability(
                target_alias=TARGET_ALIAS,
                capability=LIGHT_EXECUTION_CAPABILITY,
                control_owner=CONTROL_OWNER,
                allowed_desired_states=(),
                desired_state_validator=lambda value: isinstance(
                    value,
                    _TrialBrightnessState,
                ),
                maximum_state_age=maximum_state_age,
                approval_required=True,
            ),
        )
    ).execute(
        intent,
        evidence=evidence,
        authorization=authorization,
        evaluated_at=evaluated_at,
    )
    return (
        result.outcome is ExecutionOutcome.WOULD_DISPATCH
        and result.dispatch_attempted is False
    )


def _command_accepted(response: dict[str, Any]) -> bool:
    return response.get("statusCode") == 100
