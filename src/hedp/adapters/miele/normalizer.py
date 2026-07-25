from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


MISSING_SENTINEL = -32_768


@dataclass(frozen=True)
class MieleReading:
    status_code: int | None
    program_id: int | None
    program_type_code: int | None
    program_phase_code: int | None
    remaining_minutes: int | None
    elapsed_minutes: int | None
    scheduled_start_minutes_of_day: int | None
    temperature_c: int | float | None
    spin_speed_rpm: int | float | None
    drying_step_code: int | None

    def safe_payload(self) -> dict[str, int | float | None]:
        return asdict(self)


def _number(value: Any) -> int | float | None:
    if isinstance(value, dict):
        value = value.get("value_raw")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return None if value == MISSING_SENTINEL else value


def _integer(value: Any) -> int | None:
    number = _number(value)
    return number if isinstance(number, int) else None


def _minutes(value: Any) -> int | None:
    if not isinstance(value, list) or len(value) != 2:
        return None
    hours, minutes = value
    if (
        isinstance(hours, bool)
        or isinstance(minutes, bool)
        or not isinstance(hours, int)
        or not isinstance(minutes, int)
        or hours < 0
        or not 0 <= minutes < 60
    ):
        return None
    return hours * 60 + minutes


def normalize_washer_dryer(device: object) -> MieleReading:
    if not isinstance(device, dict):
        raise ValueError("washer-dryer response must be an object")
    state = device.get("state")
    if not isinstance(state, dict):
        raise ValueError("washer-dryer state is missing")
    return MieleReading(
        status_code=_integer(state.get("status")),
        program_id=_integer(state.get("ProgramID")),
        program_type_code=_integer(state.get("programType")),
        program_phase_code=_integer(state.get("programPhase")),
        remaining_minutes=_minutes(state.get("remainingTime")),
        elapsed_minutes=_minutes(state.get("elapsedTime")),
        scheduled_start_minutes_of_day=_minutes(state.get("startTime")),
        temperature_c=_number(state.get("temperature")),
        spin_speed_rpm=_number(state.get("spinningSpeed")),
        drying_step_code=_integer(state.get("dryingStep")),
    )
