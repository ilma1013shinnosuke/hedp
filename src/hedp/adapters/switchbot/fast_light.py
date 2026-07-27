"""Low-latency SwitchBot light command output ports.

The caller is responsible for authorization and ExecutionGate checks.  This
port deliberately performs one signed POST only: it never lists devices,
reads state, retries, or performs an implicit compensation command.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import quote

import requests

from .client import SwitchBotClient


class FastLightTransportError(RuntimeError):
    """Sanitized command failure which never includes a vendor URL or ID."""

    def __init__(self, reason_code: str) -> None:
        if reason_code not in {
            "timeout",
            "connection_failed",
            "http_rejected",
            "response_invalid",
        }:
            raise ValueError("unsupported fast-light failure reason")
        self.reason_code = reason_code
        super().__init__(f"SwitchBot light command failed: {reason_code}")


class FastLightCommand(StrEnum):
    TURN_ON = "turnOn"
    TURN_OFF = "turnOff"
    SET_BRIGHTNESS = "setBrightness"
    SET_COLOR_TEMPERATURE = "setColorTemperature"
    SET_COLOR = "setColor"


# Compatibility name retained for existing E26 callers.
FastE26Command = FastLightCommand


@dataclass(frozen=True)
class FastCommandReceipt:
    target_alias: str
    command: FastLightCommand
    accepted: bool
    receipt_ms: float
    attempts: int = 1

    def safe_summary(self) -> dict[str, object]:
        return {
            "target_alias": self.target_alias,
            "command": self.command.value,
            "accepted": self.accepted,
            "receipt_ms": round(self.receipt_ms, 1),
            "attempts": self.attempts,
            "pre_read": False,
            "post_read": False,
        }


class FastLightCommandTransport:
    """Send one validated light command without discovery or read-back."""

    BASE_URL = "https://api.switch-bot.com/v1.1"

    def __init__(
        self,
        token: str,
        secret: str,
        vendor_device_id: str,
        *,
        target_alias: str,
        supported_commands: frozenset[FastLightCommand],
        minimum_brightness: int,
        timeout_seconds: float = 2.0,
        request_post: Callable[..., requests.Response] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not token or not secret:
            raise ValueError("SwitchBot credentials are required")
        if not vendor_device_id:
            raise ValueError("light device binding is required")
        if not target_alias or not target_alias.isascii():
            raise ValueError("target_alias must be a non-empty ASCII value")
        if not supported_commands:
            raise ValueError("supported_commands must not be empty")
        if minimum_brightness not in {0, 1}:
            raise ValueError("minimum_brightness must be 0 or 1")
        if not 0 < timeout_seconds <= 5:
            raise ValueError("timeout_seconds must be greater than 0 and at most 5")
        self._signer = SwitchBotClient(
            token,
            secret,
            timeout_seconds=timeout_seconds,
        )
        self._target_alias = target_alias
        self._supported_commands = supported_commands
        self._minimum_brightness = minimum_brightness
        self._encoded_device_id = quote(vendor_device_id, safe="")
        self._timeout_seconds = timeout_seconds
        if request_post is None:
            self._session: requests.Session | None = requests.Session()
            self._request_post = self._session.post
        else:
            self._session = None
            self._request_post = request_post
        self._monotonic = monotonic

    def send(
        self,
        command: FastLightCommand,
        parameter: str = "default",
    ) -> FastCommandReceipt:
        if not isinstance(command, FastLightCommand):
            raise TypeError("command must be FastLightCommand")
        if command not in self._supported_commands:
            raise ValueError("command is not supported by this light")
        parameter = _validated_parameter(
            command,
            parameter,
            minimum_brightness=self._minimum_brightness,
        )
        started_at = self._monotonic()
        try:
            response = self._request_post(
                f"{self.BASE_URL}/devices/{self._encoded_device_id}/commands",
                headers=self._signer.authentication_headers(),
                json={
                    "command": command.value,
                    "parameter": parameter,
                    "commandType": "command",
                },
                timeout=self._timeout_seconds,
            )
        except requests.Timeout as error:
            raise FastLightTransportError("timeout") from error
        except requests.ConnectionError as error:
            raise FastLightTransportError("connection_failed") from error
        except requests.RequestException as error:
            raise FastLightTransportError("http_rejected") from error
        receipt_ms = (self._monotonic() - started_at) * 1000
        try:
            response.raise_for_status()
        except requests.RequestException as error:
            raise FastLightTransportError("http_rejected") from error
        try:
            payload: Any = response.json()
        except (TypeError, ValueError) as error:
            raise FastLightTransportError("response_invalid") from error
        if not isinstance(payload, dict):
            raise FastLightTransportError("response_invalid")
        accepted = payload.get("statusCode") == 100
        return FastCommandReceipt(
            target_alias=self._target_alias,
            command=command,
            accepted=accepted,
            receipt_ms=receipt_ms,
        )


_LIGHT_COMMANDS = frozenset(FastLightCommand)


class E26FastCommandTransport(FastLightCommandTransport):
    """Send one validated E26 command without discovery or read-back."""

    def __init__(
        self,
        token: str,
        secret: str,
        vendor_device_id: str,
        *,
        timeout_seconds: float = 2.0,
        request_post: Callable[..., requests.Response] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(
            token,
            secret,
            vendor_device_id,
            target_alias="e26-smart-bulb",
            supported_commands=_LIGHT_COMMANDS,
            minimum_brightness=1,
            timeout_seconds=timeout_seconds,
            request_post=request_post,
            monotonic=monotonic,
        )


class StripLight3FastCommandTransport(FastLightCommandTransport):
    """Send one validated Strip Light 3 command without discovery or read-back."""

    def __init__(
        self,
        token: str,
        secret: str,
        vendor_device_id: str,
        *,
        timeout_seconds: float = 2.0,
        request_post: Callable[..., requests.Response] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(
            token,
            secret,
            vendor_device_id,
            target_alias="strip-light-3",
            supported_commands=_LIGHT_COMMANDS,
            minimum_brightness=0,
            timeout_seconds=timeout_seconds,
            request_post=request_post,
            monotonic=monotonic,
        )


def _validated_parameter(
    command: FastLightCommand,
    parameter: str,
    *,
    minimum_brightness: int,
) -> str:
    if command in {FastLightCommand.TURN_ON, FastLightCommand.TURN_OFF}:
        if parameter != "default":
            raise ValueError("power commands require the default parameter")
        return parameter

    if command is FastLightCommand.SET_BRIGHTNESS:
        return str(
            _bounded_integer(
                parameter,
                name="brightness",
                minimum=minimum_brightness,
                maximum=100,
            )
        )

    if command is FastLightCommand.SET_COLOR_TEMPERATURE:
        return str(
            _bounded_integer(
                parameter,
                name="color temperature",
                minimum=2700,
                maximum=6500,
            )
        )

    if command is FastLightCommand.SET_COLOR:
        parts = parameter.split(":")
        if len(parts) != 3:
            raise ValueError("color must be R:G:B")
        values = [
            _bounded_integer(value, name="color channel", minimum=0, maximum=255)
            for value in parts
        ]
        return ":".join(str(value) for value in values)

    raise ValueError("unsupported light command")


def _bounded_integer(value: str, *, name: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be an integer") from error
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be from {minimum} to {maximum}")
    return parsed
