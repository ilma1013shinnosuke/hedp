"""Normalize already-acquired Qrio cloud responses without API access."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256

from hedp.observations import (
    ObservationTime,
    ObservedValue,
    Quality,
    require_aware_datetime,
)

from .models import (
    BatteryState,
    LockAction,
    LockEvent,
    LockEventBatch,
    LockHealth,
    LockHealthBatch,
    LockPosition,
    LockStatus,
)


_BATTERY_STATES = {
    0: BatteryState.OK,
    1: BatteryState.OK,
    2: BatteryState.LOW,
    3: BatteryState.REPLACE,
    4: BatteryState.REPLACE,
    5: BatteryState.EMPTY,
    6: BatteryState.INVALID_VOLTAGE,
}


def normalize_status(
    response: object,
    *,
    target_ref: str,
    time: ObservationTime,
) -> LockStatus:
    payload = _payload(response)
    if payload is None:
        reading = ObservedValue[LockPosition](
            None,
            Quality.INVALID,
            "response_not_object",
        )
    else:
        value = payload.get("main_lock")
        if value == 1:
            reading = ObservedValue(LockPosition.UNLOCKED, Quality.GOOD)
        elif value == 2:
            reading = ObservedValue(LockPosition.LOCKED, Quality.GOOD)
        elif "main_lock" not in payload:
            reading = ObservedValue(None, Quality.MISSING, "main_lock_missing")
        else:
            reading = ObservedValue(None, Quality.UNKNOWN, "main_lock_unknown")
    return LockStatus(target_ref, reading, time)


def normalize_health(
    response: object,
    *,
    aliases: Mapping[str, str],
    time: ObservationTime,
) -> LockHealthBatch:
    payload = _payload(response)
    if payload is None:
        return LockHealthBatch((), Quality.INVALID, time, invalid_count=1)
    rows = payload.get("data")
    if not isinstance(rows, list):
        return LockHealthBatch((), Quality.MISSING, time)

    items: list[LockHealth] = []
    invalid_count = 0
    unmapped_count = 0
    for item in rows:
        if not isinstance(item, Mapping) or not isinstance(item.get("lock"), Mapping):
            invalid_count += 1
            continue
        lock = item["lock"]
        source_id = lock.get("id")
        if not isinstance(source_id, str):
            invalid_count += 1
            continue
        target_ref = aliases.get(source_id)
        if target_ref is None:
            unmapped_count += 1
            continue
        setting = lock.get("lock_setting")
        if not isinstance(setting, Mapping):
            setting = {}
        hub = setting.get("hub")
        hub_mapping = hub if isinstance(hub, Mapping) else None
        items.append(
            LockHealth(
                target_ref,
                _string(lock, "fw_version"),
                _battery(lock.get("battery_a")),
                _battery(lock.get("battery_b")),
                ObservedValue(hub_mapping is not None, Quality.GOOD),
                (
                    _string(hub_mapping, "fw_version")
                    if hub_mapping is not None
                    else ObservedValue(None, Quality.MISSING, "hub_not_registered")
                ),
                _boolean(lock, "enable_sound"),
                _boolean(lock, "enable_autolock"),
                _boolean(lock, "enable_autolock_sound"),
                _integer(lock, "beacon_interval"),
                time,
            )
        )
    quality = _batch_quality(invalid_count, unmapped_count)
    return LockHealthBatch(
        tuple(items),
        quality,
        time,
        invalid_count,
        unmapped_count,
    )


def normalize_history(
    response: object,
    *,
    target_ref: str,
    received_at: str,
) -> LockEventBatch:
    require_aware_datetime("received_at", received_at)
    payload = _payload(response)
    if payload is None:
        return LockEventBatch((), Quality.INVALID, received_at, invalid_count=1)
    rows = payload.get("display_logs")
    if not isinstance(rows, list):
        return LockEventBatch((), Quality.MISSING, received_at)

    items: list[LockEvent] = []
    invalid_count = 0
    for row in rows:
        if not isinstance(row, Mapping):
            invalid_count += 1
            continue
        vendor_id = row.get("id")
        observed_at = row.get("logged_at")
        if not isinstance(vendor_id, str) or not isinstance(observed_at, str):
            invalid_count += 1
            continue
        try:
            time = ObservationTime(observed_at.replace("Z", "+00:00"), received_at)
        except (TypeError, ValueError):
            invalid_count += 1
            continue
        action_value = row.get("integrated_behavior")
        if action_value == "open":
            action = ObservedValue(LockAction.UNLOCKED, Quality.GOOD)
        elif action_value == "close":
            action = ObservedValue(LockAction.LOCKED, Quality.GOOD)
        else:
            action = ObservedValue(None, Quality.UNKNOWN, "lock_action_unknown")
        items.append(
            LockEvent(
                target_ref,
                sha256(vendor_id.encode("utf-8")).hexdigest(),
                action,
                time,
            )
        )
    quality = Quality.INVALID if invalid_count else Quality.GOOD
    if any(item.action.quality != Quality.GOOD for item in items):
        quality = Quality.UNKNOWN
    return LockEventBatch(tuple(items), quality, received_at, invalid_count)


def _payload(response: object) -> Mapping[object, object] | None:
    if not isinstance(response, Mapping):
        return None
    data = response.get("data")
    return data if isinstance(data, Mapping) else response


def _string(mapping: Mapping[object, object], key: str) -> ObservedValue[str]:
    value = mapping.get(key)
    if value is None:
        return ObservedValue(None, Quality.MISSING, f"{key}_missing")
    if not isinstance(value, str):
        return ObservedValue(None, Quality.INVALID, f"{key}_invalid")
    return ObservedValue(value, Quality.GOOD)


def _boolean(mapping: Mapping[object, object], key: str) -> ObservedValue[bool]:
    value = mapping.get(key)
    if value is None:
        return ObservedValue(None, Quality.MISSING, f"{key}_missing")
    if not isinstance(value, bool):
        return ObservedValue(None, Quality.INVALID, f"{key}_invalid")
    return ObservedValue(value, Quality.GOOD)


def _integer(mapping: Mapping[object, object], key: str) -> ObservedValue[int]:
    value = mapping.get(key)
    if value is None:
        return ObservedValue(None, Quality.MISSING, f"{key}_missing")
    if isinstance(value, bool) or not isinstance(value, int):
        return ObservedValue(None, Quality.INVALID, f"{key}_invalid")
    return ObservedValue(value, Quality.GOOD)


def _battery(value: object) -> ObservedValue[BatteryState]:
    if value is None:
        return ObservedValue(None, Quality.MISSING, "battery_missing")
    if isinstance(value, bool):
        return ObservedValue(None, Quality.INVALID, "battery_invalid")
    try:
        code = int(value)
    except (TypeError, ValueError):
        return ObservedValue(None, Quality.INVALID, "battery_invalid")
    state = _BATTERY_STATES.get(code)
    if state is None:
        return ObservedValue(None, Quality.UNKNOWN, "battery_code_unknown")
    return ObservedValue(state, Quality.GOOD)


def _batch_quality(invalid_count: int, unmapped_count: int) -> Quality:
    if invalid_count:
        return Quality.INVALID
    if unmapped_count:
        return Quality.UNKNOWN
    return Quality.GOOD
