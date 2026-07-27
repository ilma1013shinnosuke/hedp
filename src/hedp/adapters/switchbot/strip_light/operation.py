"""Formal SwitchBot Strip Light 3 read and execution boundaries.

Only the public SwitchBot OpenAPI vocabulary is admitted here.  Reading and
writing use separate injected ports.  A write is authorized by the common
ExecutionGate, dispatched once, and verified by one fresh read-back.  Neither
the adapter nor its transports retry an operation.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from threading import Lock
from typing import Any, Protocol
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


TARGET_ALIAS = "strip-light-3"
EXPECTED_DEVICE_TYPE = "Strip Light 3"
CONTROL_OWNER = "hestia"


class StripLightCapabilityStatus(StrEnum):
    FORMAL = "formal"
    UNSUPPORTED = "unsupported"
    EXPERIMENTAL = "experimental"


@dataclass(frozen=True)
class StripLightCapability:
    name: str
    status: StripLightCapabilityStatus
    representation: str
    readback: str
    reason: str

    def safe_summary(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status.value,
            "representation": self.representation,
            "readback": self.readback,
            "reason": self.reason,
        }


def strip_light_3_capabilities() -> tuple[StripLightCapability, ...]:
    """Return the public capability boundary without household identifiers."""

    return (
        StripLightCapability(
            "power",
            StripLightCapabilityStatus.FORMAL,
            "on_off",
            "openapi_status_field",
            "official_openapi_and_local_acceptance_confirmed",
        ),
        StripLightCapability(
            "brightness",
            StripLightCapabilityStatus.FORMAL,
            "integer_1_100",
            "openapi_status_field",
            "zero_is_not_exposed_as_formal_brightness",
        ),
        StripLightCapability(
            "color",
            StripLightCapabilityStatus.FORMAL,
            "rgb_0_255_per_channel",
            "openapi_status_field_without_active_mode",
            "official_openapi_and_local_visual_confirmation",
        ),
        StripLightCapability(
            "color_temperature",
            StripLightCapabilityStatus.FORMAL,
            "kelvin_2700_6500",
            "openapi_status_field_without_active_mode",
            "official_openapi_and_local_acceptance_confirmed",
        ),
        StripLightCapability(
            "device_effect",
            StripLightCapabilityStatus.UNSUPPORTED,
            "none",
            "not_available_in_public_openapi",
            "app_only_for_hestia_scope",
        ),
        StripLightCapability(
            "music",
            StripLightCapabilityStatus.UNSUPPORTED,
            "none",
            "not_available_in_public_openapi",
            "app_or_device_controller_only",
        ),
        StripLightCapability(
            "account_automation_scene",
            StripLightCapabilityStatus.UNSUPPORTED,
            "separate_account_domain",
            "not_a_device_effect_readback",
            "not_part_of_strip_light_device_adapter",
        ),
    )


@dataclass(frozen=True)
class StripLight3State:
    """Anonymous, normalized status used by the gate and read-back verifier."""

    power: LightPower
    brightness: int
    color: RgbColor
    color_temperature: int
    observed_at: datetime
    quality: EvidenceQuality = EvidenceQuality.GOOD
    target_alias: str = TARGET_ALIAS

    def __post_init__(self) -> None:
        if self.target_alias != TARGET_ALIAS:
            raise ValueError("Strip Light 3 state belongs to an unsupported target")
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
        if (
            not isinstance(self.observed_at, datetime)
            or self.observed_at.tzinfo is None
            or self.observed_at.utcoffset() is None
        ):
            raise ValueError("observed_at must be timezone-aware")
        if not isinstance(self.quality, EvidenceQuality):
            raise TypeError("quality must be EvidenceQuality")

    def evidence(
        self,
        *,
        manual_override_at: datetime | None = None,
    ) -> StateEvidence:
        return StateEvidence(
            target_alias=self.target_alias,
            capability=LIGHT_EXECUTION_CAPABILITY,
            observed_at=self.observed_at,
            quality=self.quality,
            current_state=self,
            manual_override_at=manual_override_at,
        )

    def safe_summary(self) -> dict[str, object]:
        return {
            "target_alias": self.target_alias,
            "power": self.power.value,
            "brightness": self.brightness,
            "color": self.color.canonical(),
            "color_temperature": self.color_temperature,
            "observed_at": self.observed_at.isoformat(),
            "quality": self.quality.value,
        }


class StripLightReadError(RuntimeError):
    """Sanitized read failure which never carries a URL, ID, or raw response."""

    _REASONS = frozenset(
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
        if reason_code not in self._REASONS:
            raise ValueError("unsupported Strip Light read failure reason")
        self.reason_code = reason_code
        super().__init__(f"SwitchBot Strip Light state unavailable: {reason_code}")


class StripLight3StateReader(Protocol):
    """Read-only port. Implementations must perform no device command."""

    def read_state(self) -> StripLight3State: ...


class StripLight3OpenApiReader:
    """Perform one bounded status GET with no discovery, persistence, or retry."""

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
        if not token or not secret:
            raise ValueError("SwitchBot credentials are required")
        if not vendor_device_id:
            raise ValueError("Strip Light 3 device binding is required")
        if not 0 < timeout_seconds <= 5:
            raise ValueError("timeout_seconds must be greater than 0 and at most 5")
        if not 1024 <= response_byte_cap <= 1024 * 1024:
            raise ValueError("response byte cap must be between 1 KiB and 1 MiB")
        self._signer = SwitchBotClient(
            token,
            secret,
            timeout_seconds=timeout_seconds,
            max_attempts=1,
        )
        self._encoded_device_id = quote(vendor_device_id, safe="")
        self._timeout_seconds = timeout_seconds
        self._response_byte_cap = response_byte_cap
        self._clock = clock
        if request_get is None:
            self._session: requests.Session | None = requests.Session()
            self._request_get = self._session.get
        else:
            self._session = None
            self._request_get = request_get

    def read_state(self) -> StripLight3State:
        try:
            response = self._request_get(
                f"{self.BASE_URL}/devices/{self._encoded_device_id}/status",
                headers=self._signer.authentication_headers(),
                timeout=self._timeout_seconds,
                stream=True,
            )
        except requests.Timeout as error:
            raise StripLightReadError("timeout") from error
        except requests.ConnectionError as error:
            raise StripLightReadError("connection_failed") from error
        except requests.RequestException as error:
            raise StripLightReadError("http_rejected") from error
        try:
            response.raise_for_status()
        except requests.RequestException as error:
            raise StripLightReadError("http_rejected") from error
        payload = self._bounded_json(response)
        observed_at = self._clock()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return parse_strip_light_3_status(payload, observed_at=observed_at)

    def _bounded_json(self, response: requests.Response) -> dict[str, Any]:
        declared = response.headers.get("Content-Length")
        if declared is not None:
            try:
                if int(declared) > self._response_byte_cap:
                    raise StripLightReadError("response_too_large")
            except ValueError as error:
                raise StripLightReadError("response_invalid") from error
        content = bytearray()
        try:
            for chunk in response.iter_content(chunk_size=4096):
                if not chunk:
                    continue
                content.extend(chunk)
                if len(content) > self._response_byte_cap:
                    raise StripLightReadError("response_too_large")
            value = json.loads(bytes(content))
        except StripLightReadError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
            raise StripLightReadError("response_invalid") from error
        if not isinstance(value, dict):
            raise StripLightReadError("response_invalid")
        return value


def parse_strip_light_3_status(
    payload: object,
    *,
    observed_at: datetime,
) -> StripLight3State:
    """Parse one anonymous OpenAPI fixture or bounded live response."""

    if not isinstance(payload, dict):
        raise StripLightReadError("response_invalid")
    if payload.get("statusCode") != 100:
        raise StripLightReadError("vendor_rejected")
    body = payload.get("body")
    if not isinstance(body, dict):
        raise StripLightReadError("response_invalid")
    if body.get("deviceType") != EXPECTED_DEVICE_TYPE:
        raise StripLightReadError("device_type_mismatch")
    power = body.get("power")
    brightness = body.get("brightness")
    color_temperature = body.get("colorTemperature")
    try:
        normalized_power = {
            "on": LightPower.ON,
            "off": LightPower.OFF,
        }[power.strip().casefold()]
        normalized_color = _parse_rgb(body.get("color"))
        return StripLight3State(
            normalized_power,
            brightness,
            normalized_color,
            color_temperature,
            observed_at,
        )
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise StripLightReadError("state_invalid") from error


def _parse_rgb(value: object) -> RgbColor:
    if not isinstance(value, str):
        raise TypeError("RGB status must be a string")
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError("RGB status must have three channels")
    return RgbColor(*(int(part) for part in parts))


class StripLight3OperationAdapter(ExecutionCoordinator):
    """ExecutionGate-compatible coordinator with one-shot physical read-back.

    The class intentionally subclasses the vendor-neutral coordinator so the
    existing low-latency ``FastLightControlSession`` can use this formal path
    without a parallel slider dispatcher.
    """

    def __init__(
        self,
        command_transport: FastLightCommandTransport,
        verification_reader: StripLight3StateReader,
        *,
        control_owner: str = CONTROL_OWNER,
        maximum_state_age: timedelta = timedelta(seconds=5),
        duplicate_window_seconds: float = 0.25,
        monotonic: Callable[[], float] = time.monotonic,
        latency_monotonic: Callable[[], float] = time.perf_counter,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if not isinstance(command_transport, FastLightCommandTransport):
            raise TypeError("command_transport must be FastLightCommandTransport")
        if not callable(getattr(verification_reader, "read_state", None)):
            raise TypeError("verification_reader must implement read_state")
        if not timedelta(0) < maximum_state_age <= timedelta(minutes=5):
            raise ValueError("maximum_state_age must be positive and at most 5 minutes")
        if not 0 <= duplicate_window_seconds <= 1:
            raise ValueError("duplicate window must be between 0 and 1 second")
        capability = ExecutionCapability(
            target_alias=TARGET_ALIAS,
            capability=LIGHT_EXECUTION_CAPABILITY,
            control_owner=control_owner,
            allowed_desired_states=(),
            desired_state_validator=_formal_desired_state,
            maximum_state_age=maximum_state_age,
            approval_required=True,
        )
        port = FastLightExecutionPort(command_transport, target_alias=TARGET_ALIAS)
        super().__init__(
            (capability,),
            {(TARGET_ALIAS, LIGHT_EXECUTION_CAPABILITY): port},
        )
        self._verification_reader = verification_reader
        self._maximum_state_age = maximum_state_age
        self._duplicate_window_seconds = duplicate_window_seconds
        self._monotonic = monotonic
        self._latency_monotonic = latency_monotonic
        self._clock = clock
        self._adapter_lock = Lock()
        self._last_dispatch: tuple[tuple[str, str | int], float] | None = None
        self._last_fast_execute_ms: float | None = None
        self._safety_stop_reason: str | None = None
        self._verification_claims: set[str] = set()

    @property
    def safety_stopped(self) -> bool:
        with self._adapter_lock:
            return self._safety_stop_reason is not None

    @property
    def last_fast_execute_ms(self) -> float | None:
        """Gate-plus-send latency; deliberately excludes physical read-back."""

        with self._adapter_lock:
            return self._last_fast_execute_ms

    def resume_after_resynchronization(
        self,
        state: StripLight3State,
        *,
        evaluated_at: datetime,
    ) -> None:
        """Clear a result-unknown stop only after a fresh, good external read."""

        if not isinstance(state, StripLight3State):
            raise TypeError("state must be StripLight3State")
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if (
            state.quality is not EvidenceQuality.GOOD
            or state.observed_at > evaluated_at
            or evaluated_at - state.observed_at > self._maximum_state_age
        ):
            raise PermissionError("resynchronization state quality is insufficient")
        with self._adapter_lock:
            self._safety_stop_reason = None
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
        if mode is not ExecutionMode.LIVE:
            return _locally_stopped(intent, "formal_adapter_requires_live_mode")
        state = evidence.current_state if evidence is not None else None
        if (
            not isinstance(state, StripLight3State)
            or state.observed_at != evidence.observed_at
            or state.quality is not evidence.quality
        ):
            return _locally_stopped(
                intent,
                "typed_state_evidence_required",
                status=GateStatus.UNAVAILABLE,
            )
        with self._adapter_lock:
            if self._safety_stop_reason is not None:
                return _locally_stopped(intent, "adapter_safety_stopped")
        desired = intent.desired_state
        if not isinstance(desired, LightDesiredState):
            return _locally_stopped(intent, "desired_state_invalid")
        if (
            state.power is LightPower.OFF
            and desired.command is not LightCommand.SET_POWER
        ):
            return _locally_stopped(intent, "power_off_requires_explicit_power_on")
        if _safe_noop_match(state, desired):
            return _no_operation_completed(intent)

        fingerprint = (desired.command.value, desired.canonical_value())
        now = self._monotonic()
        with self._adapter_lock:
            if (
                self._last_dispatch is not None
                and self._last_dispatch[0] == fingerprint
                and now - self._last_dispatch[1] <= self._duplicate_window_seconds
            ):
                return _locally_stopped(intent, "duplicate_desired_state")
            # Claim before dispatch. It is retained after timeout because the
            # command may have reached the device.
            self._last_dispatch = (fingerprint, now)

        dispatched = super().execute(
            intent,
            evidence=evidence,
            authorization=authorization,
            evaluated_at=evaluated_at,
            mode=mode,
            manual_override_cooldown=manual_override_cooldown,
        )
        finished = self._latency_monotonic()
        with self._adapter_lock:
            self._last_fast_execute_ms = max(0.0, finished - started) * 1000
        if dispatched.outcome is not ExecutionOutcome.PENDING_VERIFICATION:
            if (
                dispatched.dispatch_attempted
                and dispatched.outcome is ExecutionOutcome.UNKNOWN
            ):
                self._latch_safety_stop("result_unknown")
            return dispatched
        return dispatched

    def verify(
        self,
        intent: Intent,
        *,
        precondition: StripLight3State,
        dispatched: ExecutionResult,
        evaluated_at: datetime,
    ) -> ExecutionResult:
        """Perform the separate one-shot read-back phase.

        A verification claim is never released.  Repeating a failed or unknown
        read is therefore impossible through this adapter instance.
        """

        if dispatched.outcome is not ExecutionOutcome.PENDING_VERIFICATION:
            return dispatched
        if not dispatched.dispatch_attempted:
            raise ValueError("verification requires one attempted dispatch")
        if (
            not dispatched.audit_events
            or dispatched.audit_events[-1].operation_id != intent.operation_id
            or dispatched.audit_events[-1].target_alias != intent.target_alias
            or dispatched.audit_events[-1].capability != intent.capability
        ):
            raise ValueError("verification intent does not match dispatch result")
        if not isinstance(precondition, StripLight3State):
            raise TypeError("precondition must be StripLight3State")
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        with self._adapter_lock:
            if intent.operation_id in self._verification_claims:
                return _locally_stopped(intent, "duplicate_verification")
            self._verification_claims.add(intent.operation_id)
        desired = intent.desired_state
        if not isinstance(desired, LightDesiredState):
            raise TypeError("intent desired state must be LightDesiredState")
        try:
            observed = self._verification_reader.read_state()
        except Exception:
            self._latch_safety_stop("readback_unavailable")
            return _finalize(
                dispatched,
                ExecutionOutcome.UNKNOWN,
                "accepted",
                "unavailable",
                "result_unknown",
            )
        verified_at = self._clock()
        if verified_at.tzinfo is None or verified_at.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        if (
            observed.quality is not EvidenceQuality.GOOD
            or observed.observed_at < evaluated_at
            or observed.observed_at > verified_at
            or verified_at - observed.observed_at > self._maximum_state_age
        ):
            self._latch_safety_stop("readback_not_fresh_good")
            return _finalize(
                dispatched,
                ExecutionOutcome.UNKNOWN,
                "accepted",
                "unavailable",
                "result_unknown",
            )
        if not _desired_matches(observed, desired):
            self._latch_safety_stop("readback_not_matched")
            return _finalize(
                dispatched,
                ExecutionOutcome.FAILED,
                "accepted",
                "not_matched",
                "readback_not_matched",
            )
        if (
            desired.command
            in {LightCommand.SET_COLOR, LightCommand.SET_COLOR_TEMPERATURE}
            and _field_value(precondition, desired.command)
            == _field_value(observed, desired.command)
        ):
            # OpenAPI exposes the stored RGB/CCT fields but no active-mode
            # field. An unchanged stored value cannot prove a mode transition.
            self._latch_safety_stop("active_mode_not_observable")
            return _finalize(
                dispatched,
                ExecutionOutcome.UNKNOWN,
                "accepted",
                "unavailable",
                "active_mode_not_observable",
            )
        return _finalize(
            dispatched,
            ExecutionOutcome.COMPLETED,
            "accepted",
            "matched",
            "readback_matched",
        )

    def execute_and_verify(
        self,
        intent: Intent,
        *,
        evidence: StateEvidence,
        authorization: Authorization,
        evaluated_at: datetime,
        manual_override_cooldown: timedelta = timedelta(0),
    ) -> ExecutionResult:
        """Synchronous single-operation helper outside the fast slider path."""

        result = self.execute(
            intent,
            evidence=evidence,
            authorization=authorization,
            evaluated_at=evaluated_at,
            mode=ExecutionMode.LIVE,
            manual_override_cooldown=manual_override_cooldown,
        )
        state = evidence.current_state
        if (
            result.outcome is ExecutionOutcome.PENDING_VERIFICATION
            and isinstance(state, StripLight3State)
        ):
            return self.verify(
                intent,
                precondition=state,
                dispatched=result,
                evaluated_at=evaluated_at,
            )
        return result

    def _latch_safety_stop(self, reason: str) -> None:
        with self._adapter_lock:
            self._safety_stop_reason = reason


def _formal_desired_state(value: object) -> bool:
    if not isinstance(value, LightDesiredState):
        return False
    if value.command is LightCommand.SET_BRIGHTNESS:
        return (
            isinstance(value.value, int)
            and not isinstance(value.value, bool)
            and 1 <= value.value <= 100
        )
    return value.command in {
        LightCommand.SET_POWER,
        LightCommand.SET_COLOR,
        LightCommand.SET_COLOR_TEMPERATURE,
    }


def _safe_noop_match(
    state: StripLight3State,
    desired: LightDesiredState,
) -> bool:
    # RGB and CCT are excluded: OpenAPI has no active-mode field, so equality
    # of a stored value does not prove the requested visible mode is active.
    if desired.command is LightCommand.SET_POWER:
        return state.power is desired.value
    if desired.command is LightCommand.SET_BRIGHTNESS:
        return state.brightness == desired.value
    return False


def _desired_matches(
    state: StripLight3State,
    desired: LightDesiredState,
) -> bool:
    return _field_value(state, desired.command) == desired.value


def _field_value(
    state: StripLight3State,
    command: LightCommand,
) -> LightPower | int | RgbColor:
    if command is LightCommand.SET_POWER:
        return state.power
    if command is LightCommand.SET_BRIGHTNESS:
        return state.brightness
    if command is LightCommand.SET_COLOR_TEMPERATURE:
        return state.color_temperature
    return state.color


def _locally_stopped(
    intent: Intent,
    reason: str,
    *,
    status: GateStatus = GateStatus.BLOCKED,
) -> ExecutionResult:
    outcome = {
        GateStatus.BLOCKED: ExecutionOutcome.BLOCKED,
        GateStatus.EXPIRED: ExecutionOutcome.EXPIRED,
        GateStatus.UNAVAILABLE: ExecutionOutcome.UNAVAILABLE,
    }[status]
    event = ExecutionAuditEvent(
        phase="finished",
        operation_id=intent.operation_id,
        correlation_id=intent.correlation_id,
        target_alias=intent.target_alias,
        capability=intent.capability,
        reason_code=reason,
        dispatch_attempted=False,
    )
    return ExecutionResult(
        GateDecision(status, reason),
        outcome,
        None,
        (event,),
        False,
    )


def _no_operation_completed(intent: Intent) -> ExecutionResult:
    adapter_result = AdapterExecutionResult(
        "not_dispatched",
        "already_matched",
        ExecutionOutcome.COMPLETED,
    )
    event = ExecutionAuditEvent(
        phase="finished",
        operation_id=intent.operation_id,
        correlation_id=intent.correlation_id,
        target_alias=intent.target_alias,
        capability=intent.capability,
        reason_code="semantic_duplicate_suppressed",
        dispatch_attempted=False,
    )
    return ExecutionResult(
        GateDecision(GateStatus.PASS, "conditions_satisfied"),
        ExecutionOutcome.COMPLETED,
        adapter_result,
        (event,),
        False,
    )


def _finalize(
    result: ExecutionResult,
    outcome: ExecutionOutcome,
    dispatch_status: str,
    verification_status: str,
    reason: str,
) -> ExecutionResult:
    events = result.audit_events
    if events and events[-1].phase == "finished":
        events = (*events[:-1], replace(events[-1], reason_code=reason))
    return ExecutionResult(
        result.gate,
        outcome,
        AdapterExecutionResult(
            dispatch_status,
            verification_status,
            outcome,
        ),
        events,
        result.dispatch_attempted,
    )
