"""Bounded, compensated Strip Light 3 power/temperature/RGB trial.

This is a deliberately separate live-test harness, not a general automation
path.  Every command passes through the common ExecutionGate, every stage is
read back, and a failure stops the remaining trial before a bounded
compensation sequence restores the captured state.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

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
from hedp.adapters.switchbot.secondary_state import (
    LightPower,
    RgbColor,
    SecondaryDeviceKind,
)
from hedp.operations.execution import (
    Authorization,
    ExecutionCoordinator,
    ExecutionMode,
    ExecutionOutcome,
    GateStatus,
)
from hedp.operations.shadow_execution import EvidenceQuality, Intent, StateEvidence

from .switchbot_strip_light_live_trial import (
    BoundedStripStatusTransport,
    EXPECTED_DEVICE_TYPE,
    TARGET_ALIAS,
)


CONTROL_OWNER = "hestia"
TEMPERATURE_STEP = 100
COLOR_CHANNEL_STEP = 10
MAXIMUM_COMMAND_REQUESTS = 11
MAXIMUM_STATUS_REQUESTS = 30


@dataclass(frozen=True)
class StripLightState:
    power: LightPower
    brightness: int
    color_temperature: int
    color: RgbColor


@dataclass(frozen=True)
class StripLightCapabilityTrialResult:
    reason: str
    eligible: bool
    gate_qualified: bool
    temperature_changed: bool
    temperature_restored: bool
    color_changed: bool
    color_restored: bool
    power_off_confirmed: bool
    power_on_confirmed: bool
    compensation_attempted: bool
    final_state_matches: bool
    final_power_matches: bool
    final_brightness_matches: bool
    final_temperature_matches: bool
    final_color_matches: bool
    status_requests: int
    command_requests: int

    def safe_summary(self) -> dict[str, object]:
        return {
            "target_alias": TARGET_ALIAS,
            "reason": self.reason,
            "eligible": self.eligible,
            "gate_qualified": self.gate_qualified,
            "temperature_changed": self.temperature_changed,
            "temperature_restored": self.temperature_restored,
            "color_changed": self.color_changed,
            "color_restored": self.color_restored,
            "power_off_confirmed": self.power_off_confirmed,
            "power_on_confirmed": self.power_on_confirmed,
            "compensation_attempted": self.compensation_attempted,
            "final_state_matches": self.final_state_matches,
            "final_power_matches": self.final_power_matches,
            "final_brightness_matches": self.final_brightness_matches,
            "final_temperature_matches": self.final_temperature_matches,
            "final_color_matches": self.final_color_matches,
            "status_requests": self.status_requests,
            "command_requests": self.command_requests,
            "persisted": False,
        }


class BoundedStripCapabilityCommandTransport(StripLight3FastCommandTransport):
    """Allow only the finite commands needed by this one live trial."""

    _ALLOWED = frozenset(
        {
            FastLightCommand.TURN_ON,
            FastLightCommand.TURN_OFF,
            FastLightCommand.SET_BRIGHTNESS,
            FastLightCommand.SET_COLOR_TEMPERATURE,
            FastLightCommand.SET_COLOR,
        }
    )

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
        if command not in self._ALLOWED:
            raise PermissionError("command is outside the capability trial")
        if self._command_requests >= MAXIMUM_COMMAND_REQUESTS:
            raise PermissionError("capability trial command limit reached")
        self._command_requests += 1
        return super().send(command, parameter)


class StripLightCapabilityTrial:
    """Exercise reversible light capabilities and restore the captured state."""

    def __init__(
        self,
        status_transport: BoundedStripStatusTransport,
        command_transport: BoundedStripCapabilityCommandTransport,
        *,
        vendor_device_id: str,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        sleeper: Callable[[float], None] = time.sleep,
        readback_delays: tuple[float, ...] = (0.5, 1.5, 3.0),
    ) -> None:
        if not isinstance(status_transport, BoundedStripStatusTransport):
            raise TypeError("status_transport must be BoundedStripStatusTransport")
        if not isinstance(
            command_transport, BoundedStripCapabilityCommandTransport
        ):
            raise TypeError(
                "command_transport must be BoundedStripCapabilityCommandTransport"
            )
        if not vendor_device_id:
            raise ValueError("private Strip Light 3 binding is required")
        if not readback_delays or len(readback_delays) > 3:
            raise ValueError("one to three readback delays are required")
        if any(delay < 0 or delay > 3 for delay in readback_delays):
            raise ValueError("readback delays must be between 0 and 3 seconds")
        self._status_transport = status_transport
        self._command_transport = command_transport
        self._vendor_device_id = vendor_device_id
        self._clock = clock
        self._sleeper = sleeper
        self._readback_delays = readback_delays
        observed_at = self._aware_now()
        snapshot = LightCapabilitySnapshot(
            TARGET_ALIAS,
            SecondaryDeviceKind.STRIP_LIGHT_3,
            frozenset(LightCommand),
            observed_at,
            timedelta(minutes=2),
        )
        port = FastLightExecutionPort(command_transport, target_alias=TARGET_ALIAS)
        self._coordinator = ExecutionCoordinator(
            (snapshot.execution_capability(control_owner=CONTROL_OWNER),),
            {(TARGET_ALIAS, LIGHT_EXECUTION_CAPABILITY): port},
        )

    def run(self) -> StripLightCapabilityTrialResult:
        original: StripLightState | None = None
        eligible = False
        gate_qualified = False
        temperature_changed = False
        temperature_restored = False
        color_changed = False
        color_restored = False
        power_off_confirmed = False
        power_on_confirmed = False
        compensation_attempted = False
        final_matches = False
        final_field_matches = (False, False, False, False)
        reason = "trial_not_started"

        try:
            original = self._read_state()
            if original is None:
                reason = "initial_state_invalid"
                return self._result(
                    reason,
                    eligible,
                    gate_qualified,
                    temperature_changed,
                    temperature_restored,
                    color_changed,
                    color_restored,
                    power_off_confirmed,
                    power_on_confirmed,
                    compensation_attempted,
                    final_matches,
                    final_field_matches,
                )
            if original.power is not LightPower.ON:
                reason = "initial_power_off"
                return self._result(
                    reason,
                    eligible,
                    gate_qualified,
                    temperature_changed,
                    temperature_restored,
                    color_changed,
                    color_restored,
                    power_off_confirmed,
                    power_on_confirmed,
                    compensation_attempted,
                    final_matches,
                    final_field_matches,
                )
            if not _is_neutral(original.color):
                # Without an active-mode field, a colored starting state cannot
                # be proven restorable after a temperature command.
                reason = "initial_color_mode_ambiguous"
                return self._result(
                    reason,
                    eligible,
                    gate_qualified,
                    temperature_changed,
                    temperature_restored,
                    color_changed,
                    color_restored,
                    power_off_confirmed,
                    power_on_confirmed,
                    compensation_attempted,
                    final_matches,
                    final_field_matches,
                )

            eligible = True
            target_temperature = _temperature_target(original.color_temperature)
            gate_qualified = self._execute(
                LightDesiredState(
                    LightCommand.SET_COLOR_TEMPERATURE,
                    target_temperature,
                ),
                current_state=LightDesiredState(
                    LightCommand.SET_COLOR_TEMPERATURE,
                    original.color_temperature,
                ),
                reason="approved-strip-temperature-trial",
            )
            if not gate_qualified:
                reason = "temperature_gate_blocked"
                raise RuntimeError(reason)
            temperature_changed = self._wait_for(
                lambda state: state.color_temperature == target_temperature
            )
            if not temperature_changed:
                reason = "temperature_change_unconfirmed"
                raise RuntimeError(reason)

            self._execute_required(
                LightDesiredState(
                    LightCommand.SET_COLOR_TEMPERATURE,
                    original.color_temperature,
                ),
                current_state=LightDesiredState(
                    LightCommand.SET_COLOR_TEMPERATURE,
                    target_temperature,
                ),
                reason="mandatory-temperature-restore",
            )
            temperature_restored = self._wait_for(
                lambda state: state.color_temperature == original.color_temperature
            )
            if not temperature_restored:
                reason = "temperature_restore_unconfirmed"
                raise RuntimeError(reason)

            target_color = _color_target(original.color)
            self._execute_required(
                LightDesiredState(LightCommand.SET_COLOR, target_color),
                current_state=LightDesiredState(
                    LightCommand.SET_COLOR,
                    original.color,
                ),
                reason="approved-strip-rgb-trial",
            )
            color_changed = self._wait_for(lambda state: state.color == target_color)
            if not color_changed:
                reason = "color_change_unconfirmed"
                raise RuntimeError(reason)

            self._execute_required(
                LightDesiredState(LightCommand.SET_COLOR, original.color),
                current_state=LightDesiredState(LightCommand.SET_COLOR, target_color),
                reason="mandatory-color-restore",
            )
            color_restored = self._wait_for(
                lambda state: state.color == original.color
            )
            if not color_restored:
                reason = "color_restore_unconfirmed"
                raise RuntimeError(reason)

            # The vendor status has no explicit active-mode field. Reapply the
            # original temperature last so a neutral starting state returns to
            # its original visible white-temperature mode.
            self._execute_required(
                LightDesiredState(
                    LightCommand.SET_COLOR_TEMPERATURE,
                    original.color_temperature,
                ),
                current_state=LightDesiredState(
                    LightCommand.SET_COLOR,
                    original.color,
                ),
                reason="mandatory-visible-mode-restore",
            )
            if not self._wait_for(
                lambda state: state.color_temperature == original.color_temperature
            ):
                reason = "visible_mode_restore_unconfirmed"
                raise RuntimeError(reason)

            self._execute_required(
                LightDesiredState(LightCommand.SET_POWER, LightPower.OFF),
                current_state=LightDesiredState(
                    LightCommand.SET_POWER,
                    LightPower.ON,
                ),
                reason="approved-strip-power-off-trial",
            )
            power_off_confirmed = self._wait_for(
                lambda state: state.power is LightPower.OFF
            )
            if not power_off_confirmed:
                reason = "power_off_unconfirmed"
                raise RuntimeError(reason)

            self._execute_required(
                LightDesiredState(LightCommand.SET_POWER, LightPower.ON),
                current_state=LightDesiredState(
                    LightCommand.SET_POWER,
                    LightPower.OFF,
                ),
                reason="mandatory-strip-power-restore",
            )
            power_on_confirmed = self._wait_for(
                lambda state: state.power is LightPower.ON
            )
            if not power_on_confirmed:
                reason = "power_on_restore_unconfirmed"
                raise RuntimeError(reason)

            final_state = self._read_state()
            final_matches = final_state == original
            final_field_matches = _field_matches(original, final_state)
            reason = (
                "all_capabilities_changed_and_restored"
                if final_matches
                else "final_state_mismatch"
            )
        except Exception:
            if original is not None:
                compensation_attempted = True
                self._compensate(original)
                final_state = self._wait_for_state(original)
                final_matches = final_state == original
                final_field_matches = _field_matches(original, final_state)
            if reason == "trial_not_started":
                reason = "trial_error"
            reason = (
                f"{reason}_compensated"
                if final_matches
                else f"{reason}_restore_unconfirmed"
            )

        return self._result(
            reason,
            eligible,
            gate_qualified,
            temperature_changed,
            temperature_restored,
            color_changed,
            color_restored,
            power_off_confirmed,
            power_on_confirmed,
            compensation_attempted,
            final_matches,
            final_field_matches,
        )

    def _execute(
        self,
        desired: LightDesiredState,
        *,
        current_state: LightDesiredState,
        reason: str,
    ) -> bool:
        evaluated_at = self._aware_now()
        operation_id = f"stripcap-{uuid.uuid4().hex}"
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
            current_state=current_state,
        )
        result = self._coordinator.execute(
            intent,
            evidence=evidence,
            authorization=authorization,
            evaluated_at=evaluated_at,
            mode=ExecutionMode.LIVE,
        )
        return (
            result.gate.status is GateStatus.PASS
            and result.dispatch_attempted
            and result.outcome is ExecutionOutcome.PENDING_VERIFICATION
        )

    def _execute_required(
        self,
        desired: LightDesiredState,
        *,
        current_state: LightDesiredState,
        reason: str,
    ) -> None:
        if not self._execute(
            desired,
            current_state=current_state,
            reason=reason,
        ):
            raise RuntimeError("command was not accepted for verification")

    def _wait_for(self, predicate: Callable[[StripLightState], bool]) -> bool:
        for delay in self._readback_delays:
            if delay:
                self._sleeper(delay)
            state = self._read_state()
            if state is not None and predicate(state):
                return True
        return False

    def _compensate(self, original: StripLightState) -> None:
        compensation = (
            LightDesiredState(LightCommand.SET_COLOR, original.color),
            LightDesiredState(
                LightCommand.SET_COLOR_TEMPERATURE,
                original.color_temperature,
            ),
            LightDesiredState(
                LightCommand.SET_BRIGHTNESS,
                original.brightness,
            ),
            LightDesiredState(LightCommand.SET_POWER, original.power),
        )
        for desired in compensation:
            if self._command_transport.command_requests >= MAXIMUM_COMMAND_REQUESTS:
                break
            try:
                self._execute(
                    desired,
                    current_state=desired,
                    reason="bounded-strip-capability-compensation",
                )
            except Exception:
                continue

    def _read_state(self) -> StripLightState | None:
        return _parse_capability_state(
            self._status_transport.status(self._vendor_device_id)
        )

    def _safe_read(self) -> StripLightState | None:
        try:
            return self._read_state()
        except Exception:
            return None

    def _wait_for_state(
        self, expected: StripLightState
    ) -> StripLightState | None:
        last_state: StripLightState | None = None
        for delay in self._readback_delays:
            if delay:
                self._sleeper(delay)
            last_state = self._safe_read()
            if last_state == expected:
                return last_state
        return last_state

    def _result(
        self,
        reason: str,
        eligible: bool,
        gate_qualified: bool,
        temperature_changed: bool,
        temperature_restored: bool,
        color_changed: bool,
        color_restored: bool,
        power_off_confirmed: bool,
        power_on_confirmed: bool,
        compensation_attempted: bool,
        final_matches: bool,
        final_field_matches: tuple[bool, bool, bool, bool],
    ) -> StripLightCapabilityTrialResult:
        return StripLightCapabilityTrialResult(
            reason,
            eligible,
            gate_qualified,
            temperature_changed,
            temperature_restored,
            color_changed,
            color_restored,
            power_off_confirmed,
            power_on_confirmed,
            compensation_attempted,
            final_matches,
            *final_field_matches,
            self._status_transport.status_requests,
            self._command_transport.command_requests,
        )

    def _aware_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value


def _parse_capability_state(status: dict[str, Any]) -> StripLightState | None:
    body = status.get("body")
    if status.get("statusCode") != 100 or not isinstance(body, dict):
        return None
    if body.get("deviceType") != EXPECTED_DEVICE_TYPE:
        return None
    power = body.get("power")
    brightness = body.get("brightness")
    color_temperature = body.get("colorTemperature")
    color = body.get("color")
    if not isinstance(power, str) or power.strip().casefold() not in {"on", "off"}:
        return None
    if (
        isinstance(brightness, bool)
        or not isinstance(brightness, int)
        or not 0 <= brightness <= 100
    ):
        return None
    if (
        isinstance(color_temperature, bool)
        or not isinstance(color_temperature, int)
        or not 2700 <= color_temperature <= 6500
    ):
        return None
    parsed_color = _parse_color(color)
    if parsed_color is None:
        return None
    return StripLightState(
        power=(
            LightPower.ON
            if power.strip().casefold() == "on"
            else LightPower.OFF
        ),
        brightness=brightness,
        color_temperature=color_temperature,
        color=parsed_color,
    )


def _parse_color(value: object) -> RgbColor | None:
    if not isinstance(value, str):
        return None
    parts = value.split(":")
    if len(parts) != 3:
        return None
    try:
        channels = tuple(int(part) for part in parts)
        return RgbColor(*channels)
    except (TypeError, ValueError):
        return None


def _is_neutral(color: RgbColor) -> bool:
    return max(color.red, color.green, color.blue) - min(
        color.red, color.green, color.blue
    ) <= 2


def _temperature_target(value: int) -> int:
    return value + TEMPERATURE_STEP if value <= 6400 else value - TEMPERATURE_STEP


def _color_target(value: RgbColor) -> RgbColor:
    red = (
        value.red + COLOR_CHANNEL_STEP
        if value.red <= 255 - COLOR_CHANNEL_STEP
        else value.red - COLOR_CHANNEL_STEP
    )
    return RgbColor(red, value.green, value.blue)


def _field_matches(
    expected: StripLightState,
    observed: StripLightState | None,
) -> tuple[bool, bool, bool, bool]:
    if observed is None:
        return False, False, False, False
    return (
        observed.power is expected.power,
        observed.brightness == expected.brightness,
        observed.color_temperature == expected.color_temperature,
        observed.color == expected.color,
    )
