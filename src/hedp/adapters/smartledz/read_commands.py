"""Confirmed read-only Smart LEDZ 2.0.4 command shapes.

This module has no socket, scheduler, credential-store, or operating-system
dependency.  Runtime household identifiers are deliberately hidden from
``repr`` and are never retained by fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass, field


SENSOR_TYPE_CODES = (60, 61, 62)


def _integer(
    name: str,
    value: int,
    *,
    minimum: int = 0,
    maximum: int = 0xFFFF,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class ReadCommand:
    """A read request whose household-specific arguments stay out of repr."""

    command: str
    _arguments: tuple[tuple[str, object], ...] = field(repr=False)

    def payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"c": self.command}
        for name, value in self._arguments:
            payload[name] = list(value) if isinstance(value, tuple) else value
        return payload


def group_list(*, gateway_id: int) -> ReadCommand:
    return ReadCommand("GroupList", (("gateway_id", _integer("gateway_id", gateway_id)),))


def group_get(*, gateway_id: int, group_id: int) -> ReadCommand:
    return ReadCommand(
        "GroupGet",
        (
            ("gateway_id", _integer("gateway_id", gateway_id)),
            ("group_id", _integer("group_id", group_id)),
        ),
    )


def device_list(
    *,
    gateway_id: int,
    group_id: int,
    type_codes: tuple[int, ...] = SENSOR_TYPE_CODES,
) -> ReadCommand:
    if not type_codes:
        raise ValueError("type_codes must not be empty")
    validated = tuple(_integer("type_code", value) for value in type_codes)
    return ReadCommand(
        "DeviceList",
        (
            ("gateway_id", _integer("gateway_id", gateway_id)),
            ("group_id", _integer("group_id", group_id)),
            ("type_codes", validated),
        ),
    )


def device_get(*, gateway_id: int, device_id: int) -> ReadCommand:
    return ReadCommand(
        "DeviceGet",
        (
            ("gateway_id", _integer("gateway_id", gateway_id)),
            ("device_id", _integer("device_id", device_id)),
        ),
    )


def schedule_get(
    *,
    gateway_id: int,
    group_id: int,
    schedule_id: int,
) -> ReadCommand:
    return ReadCommand(
        "GroupScheduleGet",
        (
            ("gateway_id", _integer("gateway_id", gateway_id)),
            ("schedule_id", _integer("schedule_id", schedule_id)),
            ("group_id", _integer("group_id", group_id)),
        ),
    )


def sensor_lux(
    *,
    gateway_id: int,
    destination: int,
    mode: int | None = None,
) -> ReadCommand:
    arguments: list[tuple[str, object]] = [
        ("gateway_id", _integer("gateway_id", gateway_id)),
        ("dest", _integer("destination", destination)),
    ]
    if mode is not None:
        arguments.append(("mode", _integer("mode", mode)))
    return ReadCommand("DeviceSensorSwitchGetLuxValues", tuple(arguments))
