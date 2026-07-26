from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from hedp.observations import ObservationTime, ObservedValue, Quality

from .models import CollectionSource, MieleObservation
from .sse import SseEvent


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


def normalize_observation(
    device: object,
    *,
    target_ref: str,
    source: CollectionSource,
    time: ObservationTime,
) -> MieleObservation:
    """Normalize a REST snapshot or one SSE state without private text."""

    if not isinstance(device, dict):
        raise ValueError("washer-dryer response must be an object")
    state = device.get("state")
    if not isinstance(state, dict):
        raise ValueError("washer-dryer state is missing")
    fields = {
        "status_code": _observed_integer(state, "status"),
        "program_id": _observed_integer(state, "ProgramID"),
        "program_type_code": _observed_integer(state, "programType"),
        "program_phase_code": _observed_integer(state, "programPhase"),
        "remaining_minutes": _observed_minutes(state, "remainingTime"),
        "elapsed_minutes": _observed_minutes(state, "elapsedTime"),
        "scheduled_start_minutes_of_day": _observed_minutes(state, "startTime"),
        "temperature_c": _observed_number(state, "temperature"),
        "spin_speed_rpm": _observed_number(state, "spinningSpeed"),
        "drying_step_code": _observed_integer(state, "dryingStep"),
    }
    quality = (
        Quality.INVALID
        if any(value.quality == Quality.INVALID for value in fields.values())
        else (
            Quality.MISSING
            if fields["status_code"].quality == Quality.MISSING
            else Quality.GOOD
        )
    )
    return MieleObservation(
        target_ref=target_ref,
        source=source,
        time=time,
        quality=quality,
        **fields,
    )


def state_from_event(
    event: SseEvent,
    *,
    source_device_id: str,
) -> dict[str, object] | None:
    """Extract state only when it belongs to the configured type-24 device."""

    if not isinstance(source_device_id, str) or not source_device_id:
        raise ValueError("source_device_id must not be empty")
    if event.name.upper() == "PING":
        return None
    candidate = event.payload.get(source_device_id)
    if not isinstance(candidate, dict):
        return None
    state = candidate.get("state")
    ident = candidate.get("ident")
    if not isinstance(state, dict) or not isinstance(ident, dict):
        return None
    device_type = _number(ident.get("type"))
    return {"state": state} if device_type == 24 else None


def _raw_value(value: object) -> object:
    return value.get("value_raw") if isinstance(value, dict) else value


def _observed_number(
    state: dict[str, object],
    key: str,
) -> ObservedValue[int | float]:
    if key not in state or state[key] is None:
        return ObservedValue(None, Quality.MISSING, f"{key}_missing")
    value = _raw_value(state[key])
    if value == MISSING_SENTINEL:
        return ObservedValue(None, Quality.MISSING, f"{key}_sentinel")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ObservedValue(None, Quality.INVALID, f"{key}_invalid")
    return ObservedValue(value, Quality.GOOD)


def _observed_integer(
    state: dict[str, object],
    key: str,
) -> ObservedValue[int]:
    value = _observed_number(state, key)
    if value.value is None:
        return ObservedValue(None, value.quality, value.reason)
    if not isinstance(value.value, int):
        return ObservedValue(None, Quality.INVALID, f"{key}_invalid")
    return ObservedValue(value.value, Quality.GOOD)


def _observed_minutes(
    state: dict[str, object],
    key: str,
) -> ObservedValue[int]:
    if key not in state or state[key] is None:
        return ObservedValue(None, Quality.MISSING, f"{key}_missing")
    value = state[key]
    if not isinstance(value, list) or len(value) != 2:
        return ObservedValue(None, Quality.INVALID, f"{key}_invalid")
    hours, minutes = value
    if (
        isinstance(hours, bool)
        or isinstance(minutes, bool)
        or not isinstance(hours, int)
        or not isinstance(minutes, int)
        or hours < 0
        or not 0 <= minutes < 60
    ):
        return ObservedValue(None, Quality.INVALID, f"{key}_invalid")
    return ObservedValue(hours * 60 + minutes, Quality.GOOD)
