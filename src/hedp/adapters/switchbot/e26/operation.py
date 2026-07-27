"""Formal, low-latency SwitchBot E26 operation boundary.

The live path is deliberately split in two: ``execute`` performs only local
gate checks and one command POST; ``verify`` performs one bounded read-back
afterwards.  Consequently no device-list or state GET delays a valid command.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from threading import Lock
from typing import Protocol
from urllib.parse import quote

import requests

from hedp.operations.execution import (
    AdapterExecutionResult,
    Authorization,
    ExecutionAuditEvent,
    ExecutionCapability,
    ExecutionCoordinator,
    ExecutionMode,
    ExecutionOutcome,
    ExecutionResult,
    GateDecision,
    GateStatus,
)
from hedp.operations.shadow_execution import EvidenceQuality, Intent, StateEvidence

from ..client import SwitchBotClient
from ..fast_light import FastLightCommandTransport
from ..operation import (
    FastLightExecutionPort,
    LIGHT_EXECUTION_CAPABILITY,
    LightCommand,
    LightDesiredState,
)
from ..secondary_state import LightPower, RgbColor


TARGET_ALIAS = "e26-smart-bulb"
EXPECTED_DEVICE_TYPE = "Color Bulb"
CONTROL_OWNER = "hestia"


class E26CapabilityStatus(StrEnum):
    FORMAL = "formal"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class E26Capability:
    name: str
    status: E26CapabilityStatus
    representation: str
    readback: str
    reason: str


def e26_capabilities() -> tuple[E26Capability, ...]:
    return (
        E26Capability(
            "power",
            E26CapabilityStatus.FORMAL,
            "on_off",
            "openapi_status_field",
            "official_openapi_and_local_acceptance_confirmed",
        ),
        E26Capability(
            "brightness",
            E26CapabilityStatus.FORMAL,
            "integer_1_100",
            "openapi_status_field",
            "zero_is_not_a_formal_brightness",
        ),
        E26Capability(
            "color",
            E26CapabilityStatus.FORMAL,
            "rgb_0_255_per_channel",
            "openapi_status_field_without_active_mode",
            "official_openapi_and_local_visual_confirmation",
        ),
        E26Capability(
            "color_temperature",
            E26CapabilityStatus.FORMAL,
            "kelvin_2700_6500",
            "openapi_status_field_without_active_mode",
            "official_openapi_and_local_acceptance_confirmed",
        ),
        E26Capability(
            "timer",
            E26CapabilityStatus.UNSUPPORTED,
            "account_or_app_automation",
            "none",
            "not_part_of_the_low_latency_device_adapter",
        ),
        E26Capability(
            "scene_or_effect",
            E26CapabilityStatus.UNSUPPORTED,
            "none",
            "not_available_as_confirmed_device_readback",
            "unconfirmed_app_or_account_feature",
        ),
    )


@dataclass(frozen=True)
class E26State:
    power: LightPower
    brightness: int
    color: RgbColor
    color_temperature: int
    observed_at: datetime
    quality: EvidenceQuality = EvidenceQuality.GOOD
    target_alias: str = TARGET_ALIAS

    def __post_init__(self) -> None:
        if self.target_alias != TARGET_ALIAS:
            raise ValueError("E26 state belongs to an unsupported target")
        if not isinstance(self.power, LightPower):
            raise TypeError("power must be LightPower")
        if (
            isinstance(self.brightness, bool)
            or not isinstance(self.brightness, int)
            or not 1 <= self.brightness <= 100
        ):
            raise ValueError("brightness must be from 1 to 100")
        if not isinstance(self.color, RgbColor):
            raise TypeError("color must be RgbColor")
        if (
            isinstance(self.color_temperature, bool)
            or not isinstance(self.color_temperature, int)
            or not 2700 <= self.color_temperature <= 6500
        ):
            raise ValueError("color_temperature must be from 2700 to 6500")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")

    def evidence(self) -> StateEvidence:
        return StateEvidence(
            target_alias=self.target_alias,
            capability=LIGHT_EXECUTION_CAPABILITY,
            observed_at=self.observed_at,
            quality=self.quality,
            current_state=self,
        )


class E26ReadError(RuntimeError):
    """A sanitized read error that cannot leak URL, device ID, or response."""

    ALLOWED = frozenset(
        {
            "timeout",
            "connection_failed",
            "http_rejected",
            "response_too_large",
            "response_invalid",
            "vendor_rejected",
            "device_type_mismatch",
            "state_invalid",
        }
    )

    def __init__(self, reason_code: str) -> None:
        if reason_code not in self.ALLOWED:
            raise ValueError("unsupported E26 read failure")
        self.reason_code = reason_code
        super().__init__(f"SwitchBot E26 state unavailable: {reason_code}")


class E26StateReader(Protocol):
    def read_state(self) -> E26State: ...


class E26OpenApiReader:
    """One bounded status GET; no discovery, persistence, or retry."""

    BASE_URL = "https://api.switch-bot.com/v1.1"

    def __init__(
        self,
        token: str,
        secret: str,
        vendor_device_id: str,
        *,
        timeout_seconds: float = 3.0,
        response_byte_cap: int = 64 * 1024,
        request_get: Callable[..., requests.Response] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if not token or not secret or not vendor_device_id:
            raise ValueError("E26 credentials and device binding are required")
        if not 0 < timeout_seconds <= 5:
            raise ValueError("timeout_seconds must be at most 5")
        self._signer = SwitchBotClient(
            token, secret, timeout_seconds=timeout_seconds, max_attempts=1
        )
        self._device = quote(vendor_device_id, safe="")
        self._timeout = timeout_seconds
        self._cap = response_byte_cap
        self._clock = clock
        self._session = requests.Session() if request_get is None else None
        self._get = self._session.get if self._session is not None else request_get

    def read_state(self) -> E26State:
        try:
            response = self._get(
                f"{self.BASE_URL}/devices/{self._device}/status",
                headers=self._signer.authentication_headers(),
                timeout=self._timeout,
                stream=True,
            )
            response.raise_for_status()
        except requests.Timeout as error:
            raise E26ReadError("timeout") from error
        except requests.ConnectionError as error:
            raise E26ReadError("connection_failed") from error
        except requests.RequestException as error:
            raise E26ReadError("http_rejected") from error
        declared = response.headers.get("Content-Length")
        try:
            if declared is not None and int(declared) > self._cap:
                raise E26ReadError("response_too_large")
        except ValueError as error:
            raise E26ReadError("response_invalid") from error
        content = bytearray()
        try:
            for chunk in response.iter_content(chunk_size=4096):
                content.extend(chunk)
                if len(content) > self._cap:
                    raise E26ReadError("response_too_large")
            payload = json.loads(bytes(content))
        except E26ReadError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
            raise E26ReadError("response_invalid") from error
        return parse_e26_status(payload, observed_at=self._clock())


def parse_e26_status(payload: object, *, observed_at: datetime) -> E26State:
    if not isinstance(payload, dict):
        raise E26ReadError("response_invalid")
    if payload.get("statusCode") != 100:
        raise E26ReadError("vendor_rejected")
    body = payload.get("body")
    if not isinstance(body, dict):
        raise E26ReadError("response_invalid")
    if body.get("deviceType") != EXPECTED_DEVICE_TYPE:
        raise E26ReadError("device_type_mismatch")
    try:
        power = {"on": LightPower.ON, "off": LightPower.OFF}[
            body["power"].strip().casefold()
        ]
        rgb = body["color"].split(":")
        if len(rgb) != 3:
            raise ValueError
        return E26State(
            power,
            body["brightness"],
            RgbColor(*(int(part) for part in rgb)),
            body["colorTemperature"],
            observed_at,
        )
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise E26ReadError("state_invalid") from error


class E26OperationAdapter(ExecutionCoordinator):
    """Gate locally, send once immediately, then verify separately."""

    def __init__(
        self,
        transport: FastLightCommandTransport,
        verification_reader: E26StateReader,
        *,
        maximum_state_age: timedelta = timedelta(seconds=5),
        duplicate_window_seconds: float = 0.25,
        monotonic: Callable[[], float] = time.monotonic,
        latency_monotonic: Callable[[], float] = time.perf_counter,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if not isinstance(transport, FastLightCommandTransport):
            raise TypeError("transport must be FastLightCommandTransport")
        if not callable(getattr(verification_reader, "read_state", None)):
            raise TypeError("verification_reader must implement read_state")
        if not timedelta(0) < maximum_state_age <= timedelta(minutes=5):
            raise ValueError("maximum_state_age must be positive and at most 5 minutes")
        if not 0 <= duplicate_window_seconds <= 1:
            raise ValueError("duplicate window must be between 0 and 1 second")
        capability = ExecutionCapability(
            target_alias=TARGET_ALIAS,
            capability=LIGHT_EXECUTION_CAPABILITY,
            control_owner=CONTROL_OWNER,
            allowed_desired_states=(),
            desired_state_validator=_formal_desired_state,
            maximum_state_age=maximum_state_age,
            approval_required=True,
        )
        super().__init__(
            (capability,),
            {
                (TARGET_ALIAS, LIGHT_EXECUTION_CAPABILITY): FastLightExecutionPort(
                    transport, target_alias=TARGET_ALIAS
                )
            },
        )
        self._reader = verification_reader
        self._maximum_age = maximum_state_age
        self._duplicate_window = duplicate_window_seconds
        self._monotonic = monotonic
        self._latency_monotonic = latency_monotonic
        self._clock = clock
        self._lock = Lock()
        self._last_dispatch: tuple[tuple[str, str | int], float] | None = None
        self._safety_stop = False
        self._verification_claims: set[str] = set()
        self._last_fast_execute_ms: float | None = None

    @property
    def safety_stopped(self) -> bool:
        return self._safety_stop

    @property
    def last_fast_execute_ms(self) -> float | None:
        return self._last_fast_execute_ms

    def resume_after_resynchronization(
        self, state: E26State, *, evaluated_at: datetime
    ) -> None:
        """Resume only after an independent fresh, good state read."""

        if (
            state.quality is not EvidenceQuality.GOOD
            or state.observed_at > evaluated_at
            or evaluated_at - state.observed_at > self._maximum_age
        ):
            raise PermissionError("resynchronization state quality is insufficient")
        with self._lock:
            self._safety_stop = False
            self._last_dispatch = None

    def execute(
        self,
        intent: Intent,
        *,
        evidence: StateEvidence | None,
        authorization: Authorization | None,
        evaluated_at: datetime,
        mode: ExecutionMode = ExecutionMode.SHADOW,
        manual_override_cooldown: timedelta = timedelta(0),
    ) -> ExecutionResult:
        started = self._latency_monotonic()
        preflight = super().execute(
            intent,
            evidence=evidence,
            authorization=authorization,
            evaluated_at=evaluated_at,
            mode=ExecutionMode.SHADOW,
            manual_override_cooldown=manual_override_cooldown,
        )
        if preflight.outcome is not ExecutionOutcome.WOULD_DISPATCH:
            return preflight
        if mode is ExecutionMode.SHADOW:
            return preflight
        state = evidence.current_state if evidence is not None else None
        if not isinstance(state, E26State):
            return _stopped(intent, "typed_e26_state_required", GateStatus.UNAVAILABLE)
        if self._safety_stop:
            return _stopped(intent, "adapter_safety_stopped")
        desired = intent.desired_state
        if not isinstance(desired, LightDesiredState):
            return _stopped(intent, "desired_state_invalid")
        if (
            state.power is LightPower.OFF
            and desired.command is not LightCommand.SET_POWER
        ):
            return _stopped(intent, "power_off_requires_explicit_power_on")
        if _noop(state, desired):
            return _completed_without_send(intent)
        fingerprint = (desired.command.value, desired.canonical_value())
        now = self._monotonic()
        with self._lock:
            if (
                self._last_dispatch is not None
                and self._last_dispatch[0] == fingerprint
                and now - self._last_dispatch[1] <= self._duplicate_window
            ):
                return _stopped(intent, "duplicate_desired_state")
            self._last_dispatch = (fingerprint, now)
        result = super().execute(
            intent,
            evidence=evidence,
            authorization=authorization,
            evaluated_at=evaluated_at,
            mode=ExecutionMode.LIVE,
            manual_override_cooldown=manual_override_cooldown,
        )
        self._last_fast_execute_ms = (self._latency_monotonic() - started) * 1000
        if result.dispatch_attempted and result.outcome is ExecutionOutcome.UNKNOWN:
            self._safety_stop = True
        return result

    def verify(
        self,
        intent: Intent,
        *,
        precondition: E26State,
        dispatched: ExecutionResult,
        evaluated_at: datetime,
    ) -> ExecutionResult:
        if dispatched.outcome is not ExecutionOutcome.PENDING_VERIFICATION:
            return dispatched
        with self._lock:
            if intent.operation_id in self._verification_claims:
                return _stopped(intent, "duplicate_verification")
            self._verification_claims.add(intent.operation_id)
        try:
            observed = self._reader.read_state()
        except Exception:
            self._safety_stop = True
            return _finalize(dispatched, ExecutionOutcome.UNKNOWN, "unavailable")
        verified_at = self._clock()
        if (
            observed.quality is not EvidenceQuality.GOOD
            or observed.observed_at < evaluated_at
            or observed.observed_at > verified_at
            or verified_at - observed.observed_at > self._maximum_age
        ):
            self._safety_stop = True
            return _finalize(dispatched, ExecutionOutcome.UNKNOWN, "unavailable")
        desired = intent.desired_state
        if not isinstance(desired, LightDesiredState):
            raise TypeError("desired state must be LightDesiredState")
        if _field(observed, desired.command) != desired.value:
            self._safety_stop = True
            return _finalize(dispatched, ExecutionOutcome.FAILED, "not_matched")
        if desired.command in {
            LightCommand.SET_COLOR,
            LightCommand.SET_COLOR_TEMPERATURE,
        } and _field(precondition, desired.command) == _field(
            observed, desired.command
        ):
            # OpenAPI exposes stored RGB and CCT but not the active visual mode.
            self._safety_stop = True
            return _finalize(dispatched, ExecutionOutcome.UNKNOWN, "unavailable")
        return _finalize(dispatched, ExecutionOutcome.COMPLETED, "matched")

    def execute_and_verify(
        self,
        intent: Intent,
        *,
        evidence: StateEvidence,
        authorization: Authorization,
        evaluated_at: datetime,
    ) -> ExecutionResult:
        dispatched = self.execute(
            intent,
            evidence=evidence,
            authorization=authorization,
            evaluated_at=evaluated_at,
            mode=ExecutionMode.LIVE,
        )
        state = evidence.current_state
        if not isinstance(state, E26State):
            return dispatched
        return self.verify(
            intent,
            precondition=state,
            dispatched=dispatched,
            evaluated_at=evaluated_at,
        )


def _formal_desired_state(value: object) -> bool:
    if not isinstance(value, LightDesiredState):
        return False
    if value.command is LightCommand.SET_BRIGHTNESS:
        return isinstance(value.value, int) and 1 <= value.value <= 100
    return value.command in {
        LightCommand.SET_POWER,
        LightCommand.SET_COLOR,
        LightCommand.SET_COLOR_TEMPERATURE,
    }


def _noop(state: E26State, desired: LightDesiredState) -> bool:
    if desired.command is LightCommand.SET_POWER:
        return state.power is desired.value
    if desired.command is LightCommand.SET_BRIGHTNESS:
        return state.brightness == desired.value
    return False


def _field(state: E26State, command: LightCommand) -> LightPower | int | RgbColor:
    if command is LightCommand.SET_POWER:
        return state.power
    if command is LightCommand.SET_BRIGHTNESS:
        return state.brightness
    if command is LightCommand.SET_COLOR_TEMPERATURE:
        return state.color_temperature
    return state.color


def _stopped(
    intent: Intent, reason: str, status: GateStatus = GateStatus.BLOCKED
) -> ExecutionResult:
    outcome = (
        ExecutionOutcome.UNAVAILABLE
        if status is GateStatus.UNAVAILABLE
        else ExecutionOutcome.BLOCKED
    )
    event = ExecutionAuditEvent(
        "finished",
        intent.operation_id,
        intent.correlation_id,
        intent.target_alias,
        intent.capability,
        reason,
        False,
    )
    return ExecutionResult(GateDecision(status, reason), outcome, None, (event,), False)


def _completed_without_send(intent: Intent) -> ExecutionResult:
    event = ExecutionAuditEvent(
        "finished",
        intent.operation_id,
        intent.correlation_id,
        intent.target_alias,
        intent.capability,
        "semantic_duplicate_suppressed",
        False,
    )
    result = AdapterExecutionResult(
        "not_dispatched", "already_matched", ExecutionOutcome.COMPLETED
    )
    return ExecutionResult(
        GateDecision(GateStatus.ALLOWED, "already_matched"),
        ExecutionOutcome.COMPLETED,
        result,
        (event,),
        False,
    )


def _finalize(
    dispatched: ExecutionResult,
    outcome: ExecutionOutcome,
    verification: str,
) -> ExecutionResult:
    adapter = AdapterExecutionResult("accepted", verification, outcome)
    last = dispatched.audit_events[-1]
    event = replace(
        last,
        phase="finished",
        reason_code=(
            "readback_matched"
            if outcome is ExecutionOutcome.COMPLETED
            else "result_unknown"
            if outcome is ExecutionOutcome.UNKNOWN
            else "readback_not_matched"
        ),
    )
    return ExecutionResult(
        dispatched.gate,
        outcome,
        adapter,
        dispatched.audit_events + (event,),
        True,
    )
