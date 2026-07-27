"""Bounded Strip Light 3 brightness trial through the formal ExecutionGate.

The trial is intentionally narrow: it reads the bound device, changes only
brightness by five percentage points, verifies the result, restores the
original brightness, and verifies restoration.  It never changes power,
color, color temperature, scenes, registration, or device settings.
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
    ExecutionCoordinator,
    ExecutionMode,
    ExecutionOutcome,
    GateStatus,
)
from hedp.operations.shadow_execution import EvidenceQuality, Intent, StateEvidence

from hedp.adapters.switchbot.client import SwitchBotClient
from hedp.adapters.switchbot.fast_light import (
    FastCommandReceipt,
    FastLightCommand,
    StripLight3FastCommandTransport,
)
from hedp.adapters.switchbot.operation import (
    FastLightExecutionPort,
    LIGHT_EXECUTION_CAPABILITY,
    LightCapabilitySnapshot,
    LightCommand,
    LightDesiredState,
)
from hedp.adapters.switchbot.secondary_state import SecondaryDeviceKind


TARGET_ALIAS = "strip-light-3"
EXPECTED_DEVICE_TYPE = "Strip Light 3"
CONTROL_OWNER = "hestia"
BRIGHTNESS_STEP = 5
MINIMUM_TRIAL_BRIGHTNESS = 5
MAXIMUM_TRIAL_BRIGHTNESS = 95


@dataclass(frozen=True)
class StripLightTrialResult:
    """A deliberately anonymous result safe for logs and user reports."""

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
    status_requests: int
    command_requests: int

    def safe_summary(self) -> dict[str, object]:
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
            "status_requests": self.status_requests,
            "command_requests": self.command_requests,
            "persisted": False,
        }


class BoundedStripStatusTransport:
    """Read one privately bound Strip Light 3 with a hard request limit."""

    BASE_URL = "https://api.switch-bot.com/v1.1"

    def __init__(
        self,
        token: str,
        secret: str,
        *,
        timeout_seconds: float = 5,
        response_byte_cap: int = 64 * 1024,
        maximum_status_requests: int = 7,
        wall_clock_deadline_seconds: float = 45,
        request_get: Callable[..., requests.Response] = requests.get,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not token or not secret:
            raise ValueError("SwitchBot credentials are required")
        if not 0 < timeout_seconds <= 10:
            raise ValueError("timeout must be greater than 0 and at most 10 seconds")
        if not 1024 <= response_byte_cap <= 1024 * 1024:
            raise ValueError("response byte cap must be between 1 KiB and 1 MiB")
        if not 1 <= maximum_status_requests <= 30:
            raise ValueError("maximum_status_requests must be between 1 and 30")
        if not 0 < wall_clock_deadline_seconds <= 60:
            raise ValueError("wall-clock deadline must be at most 60 seconds")
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
        self._status_requests = 0

    @property
    def status_requests(self) -> int:
        return self._status_requests

    def status(self, vendor_device_id: str) -> dict[str, Any]:
        if self._status_requests >= self._maximum_status_requests:
            raise PermissionError("status request limit reached")
        if not isinstance(vendor_device_id, str) or not vendor_device_id:
            raise ValueError("vendor device identifier is required")
        self._status_requests += 1
        encoded = quote(vendor_device_id, safe="")
        timeout = min(self._timeout_seconds, self._remaining_seconds())
        response = self._request_get(
            f"{self.BASE_URL}/devices/{encoded}/status",
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


class BoundedStripCommandTransport(StripLight3FastCommandTransport):
    """Permit no more than the trial command and one compensation command."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._command_requests = 0

    @property
    def command_requests(self) -> int:
        return self._command_requests

    def send(
        self,
        command: FastLightCommand,
        parameter: str = "default",
    ) -> FastCommandReceipt:
        if self._command_requests >= 2:
            raise PermissionError("trial is limited to change and restore commands")
        if command is not FastLightCommand.SET_BRIGHTNESS:
            raise PermissionError("trial permits brightness only")
        self._command_requests += 1
        return super().send(command, parameter)


class StripLightBrightnessTrial:
    """Run one authorized and automatically compensated Strip Light 3 trial."""

    def __init__(
        self,
        status_transport: BoundedStripStatusTransport,
        command_transport: BoundedStripCommandTransport,
        *,
        vendor_device_id: str,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        sleeper: Callable[[float], None] = time.sleep,
        readback_delays: tuple[float, ...] = (0.4, 0.8, 1.2),
    ) -> None:
        if not isinstance(status_transport, BoundedStripStatusTransport):
            raise TypeError("status_transport must be BoundedStripStatusTransport")
        if not isinstance(command_transport, BoundedStripCommandTransport):
            raise TypeError("command_transport must be BoundedStripCommandTransport")
        if not isinstance(vendor_device_id, str) or not vendor_device_id:
            raise ValueError("private Strip Light 3 binding is required")
        if not readback_delays or len(readback_delays) > 3:
            raise ValueError("one to three readback delays are required")
        if any(delay < 0 or delay > 2 for delay in readback_delays):
            raise ValueError("readback delays must be between 0 and 2 seconds")
        self._status_transport = status_transport
        self._command_transport = command_transport
        self._vendor_device_id = vendor_device_id
        self._clock = clock
        self._sleeper = sleeper
        self._readback_delays = readback_delays
        snapshot_time = self._aware_now()
        snapshot = LightCapabilitySnapshot(
            TARGET_ALIAS,
            SecondaryDeviceKind.STRIP_LIGHT_3,
            frozenset({LightCommand.SET_BRIGHTNESS}),
            snapshot_time,
            timedelta(minutes=2),
        )
        port = FastLightExecutionPort(
            command_transport,
            target_alias=TARGET_ALIAS,
        )
        self._coordinator = ExecutionCoordinator(
            (snapshot.execution_capability(control_owner=CONTROL_OWNER),),
            {(TARGET_ALIAS, LIGHT_EXECUTION_CAPABILITY): port},
        )

    def run(self) -> StripLightTrialResult:
        reader_qualified = False
        writer_qualified = True
        gate_qualified = False
        eligible = False
        change_attempted = False
        change_confirmed = False
        restore_attempted = False
        restore_confirmed = False
        final_matches = False
        original_brightness: int | None = None
        reason = "trial_not_started"

        try:
            initial_state = _parse_strip_state(
                self._status_transport.status(self._vendor_device_id)
            )
            if initial_state is None:
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
            power_on, original_brightness = initial_state
            reader_qualified = True
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
            target = original_brightness + BRIGHTNESS_STEP
            changed_at = self._aware_now()
            change_result = self._execute_brightness(
                target,
                observed_brightness=original_brightness,
                evaluated_at=changed_at,
                reason="approved-strip-light-five-percent-trial",
            )
            gate_qualified = change_result.gate.status is GateStatus.PASS
            change_attempted = change_result.dispatch_attempted
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
            if change_result.outcome not in {
                ExecutionOutcome.PENDING_VERIFICATION,
                ExecutionOutcome.UNKNOWN,
            }:
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

            if change_result.outcome is ExecutionOutcome.PENDING_VERIFICATION:
                change_confirmed = self._wait_for_brightness(target)

            # Restore even after an unknown send result; the first command may
            # have reached the device despite a lost response.
            restore_attempted = True
            restored_at = self._aware_now()
            restore_result = self._execute_brightness(
                original_brightness,
                observed_brightness=target if change_confirmed else original_brightness,
                evaluated_at=restored_at,
                reason="mandatory-strip-light-trial-compensation",
            )
            if restore_result.outcome is ExecutionOutcome.PENDING_VERIFICATION:
                restore_confirmed = self._wait_for_brightness(original_brightness)
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
            if (
                change_attempted
                and not restore_attempted
                and original_brightness is not None
                and self._command_transport.command_requests < 2
            ):
                restore_attempted = True
                try:
                    restored_at = self._aware_now()
                    restore_result = self._execute_brightness(
                        original_brightness,
                        observed_brightness=original_brightness,
                        evaluated_at=restored_at,
                        reason="exception-strip-light-trial-compensation",
                    )
                    if (
                        restore_result.outcome
                        is ExecutionOutcome.PENDING_VERIFICATION
                    ):
                        restore_confirmed = self._wait_for_brightness(
                            original_brightness
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

    def _execute_brightness(
        self,
        brightness: int,
        *,
        observed_brightness: int,
        evaluated_at: datetime,
        reason: str,
    ):
        desired = LightDesiredState(LightCommand.SET_BRIGHTNESS, brightness)
        operation_id = f"striptrial-{uuid.uuid4().hex}"
        intent = Intent(
            operation_id=operation_id,
            requested_at=evaluated_at,
            expires_at=evaluated_at + timedelta(minutes=1),
            requester="user",
            reason=reason,
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
            expires_at=evaluated_at + timedelta(minutes=1),
        )
        evidence = StateEvidence(
            target_alias=TARGET_ALIAS,
            capability=LIGHT_EXECUTION_CAPABILITY,
            observed_at=evaluated_at,
            quality=EvidenceQuality.GOOD,
            current_state=LightDesiredState(
                LightCommand.SET_BRIGHTNESS,
                observed_brightness,
            ),
        )
        return self._coordinator.execute(
            intent,
            evidence=evidence,
            authorization=authorization,
            evaluated_at=evaluated_at,
            mode=ExecutionMode.LIVE,
        )

    def _wait_for_brightness(self, expected: int) -> bool:
        for delay in self._readback_delays:
            if delay:
                self._sleeper(delay)
            state = _parse_strip_state(
                self._status_transport.status(self._vendor_device_id)
            )
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
    ) -> StripLightTrialResult:
        return StripLightTrialResult(
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
            self._status_transport.status_requests,
            self._command_transport.command_requests,
        )

    def _aware_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value


def _parse_strip_state(status: dict[str, Any]) -> tuple[bool, int] | None:
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
        or not 0 <= brightness <= 100
    ):
        return None
    return normalized_power == "on", brightness
