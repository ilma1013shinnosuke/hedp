"""Privacy-safe normalization of confirmed Smart LEDZ read responses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from hedp.observations import ObservationTime, Quality


T = TypeVar("T")
AliasMap = Mapping[int, str]


@dataclass(frozen=True)
class ParsedCollection(Generic[T]):
    """A normalized collection without manufacturer identifiers or names."""

    items: tuple[T, ...]
    quality: Quality
    time: ObservationTime
    reason: str | None = None
    invalid_count: int = 0
    unmapped_count: int = 0


@dataclass(frozen=True)
class GroupState:
    target_ref: str = field(repr=False)
    power: bool
    brightness_pct: int
    fade_time: int
    quality: Quality = Quality.GOOD


@dataclass(frozen=True)
class SceneDefinition:
    target_ref: str = field(repr=False)
    icon: int
    sort_order: int
    brightness_pct: int
    color_temperature_100k: int
    rgb: int
    quality: Quality = Quality.GOOD


@dataclass(frozen=True)
class ScheduleDefinition:
    target_ref: str = field(repr=False)
    icon: int
    active: bool
    workday_mask: str = field(repr=False)
    sort_order: int
    quality: Quality = Quality.GOOD


@dataclass(frozen=True)
class ScheduleStep:
    sort_order: int
    seconds_from_midnight: int = field(repr=False)
    scene_ref: str = field(repr=False)
    scene_icon: int


@dataclass(frozen=True)
class ScheduleDetail:
    target_ref: str = field(repr=False)
    active: bool
    icon: int
    sort_order: int
    workday_mask: str = field(repr=False)
    steps: tuple[ScheduleStep, ...] = field(repr=False)
    quality: Quality = Quality.GOOD


@dataclass(frozen=True)
class DeviceReference:
    target_ref: str = field(repr=False)
    quality: Quality = Quality.GOOD


@dataclass(frozen=True)
class SensorState:
    target_ref: str = field(repr=False)
    device_type: int
    special_type_code: int
    online: bool | None
    quality: Quality = Quality.GOOD


@dataclass(frozen=True)
class IlluminanceReading:
    target_ref: str = field(repr=False)
    illuminance: int | None
    quality: Quality
    time: ObservationTime
    reason: str | None = None


@dataclass(frozen=True)
class GroupDetail:
    scenes: ParsedCollection[SceneDefinition]
    schedules: ParsedCollection[ScheduleDefinition]
    devices: ParsedCollection[DeviceReference]


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _row(value: object, minimum_length: int) -> Sequence[object] | None:
    if (
        isinstance(value, (str, bytes, bytearray))
        or not isinstance(value, Sequence)
        or len(value) < minimum_length
    ):
        return None
    return value


def _response_data(
    response: object,
    expected: type[list[object]] | type[dict[object, object]],
) -> tuple[object | None, Quality, str | None]:
    if not isinstance(response, Mapping):
        return None, Quality.INVALID, "response_not_object"
    code = response.get("ErrorCode")
    if isinstance(code, bool) or not isinstance(code, int):
        return None, Quality.MISSING, "error_code_missing_or_invalid"
    if code != 0:
        return None, Quality.UNKNOWN, "gateway_rejected_request"
    data = response.get("data")
    if not isinstance(data, expected):
        return None, Quality.MISSING, "data_missing_or_invalid"
    return data, Quality.GOOD, None


def _collection_quality(
    *,
    invalid_count: int,
    unmapped_count: int,
) -> tuple[Quality, str | None]:
    if invalid_count:
        return Quality.INVALID, "invalid_rows"
    if unmapped_count:
        return Quality.UNKNOWN, "target_alias_missing"
    return Quality.GOOD, None


def normalize_group_list(
    response: object,
    *,
    aliases: AliasMap,
    time: ObservationTime,
) -> ParsedCollection[GroupState]:
    data, quality, reason = _response_data(response, list)
    if data is None:
        return ParsedCollection((), quality, time, reason)

    items: list[GroupState] = []
    invalid_count = 0
    unmapped_count = 0
    for candidate in data:
        row = _row(candidate, 8)
        if row is None:
            invalid_count += 1
            continue
        source_id = _integer(row[0])
        fade_time = _integer(row[4])
        sort_order = _integer(row[5])
        power = _integer(row[6])
        brightness = _integer(row[7])
        if (
            source_id is None
            or fade_time is None
            or sort_order is None
            or power not in {0, 1}
            or brightness is None
            or not 0 <= brightness <= 100
        ):
            invalid_count += 1
            continue
        if sort_order < 0:
            continue
        target_ref = aliases.get(source_id)
        if target_ref is None:
            unmapped_count += 1
            continue
        items.append(GroupState(target_ref, power == 1, brightness, fade_time))

    quality, reason = _collection_quality(
        invalid_count=invalid_count,
        unmapped_count=unmapped_count,
    )
    return ParsedCollection(
        tuple(items),
        quality,
        time,
        reason,
        invalid_count,
        unmapped_count,
    )


def normalize_group_detail(
    response: object,
    *,
    scene_aliases: AliasMap,
    schedule_aliases: AliasMap,
    device_aliases: AliasMap,
    time: ObservationTime,
) -> GroupDetail:
    data, quality, reason = _response_data(response, dict)
    if data is None:
        empty: ParsedCollection[object] = ParsedCollection((), quality, time, reason)
        return GroupDetail(empty, empty, empty)  # type: ignore[arg-type]
    assert isinstance(data, Mapping)
    return GroupDetail(
        _normalize_scenes(data.get("scenes"), scene_aliases, time),
        _normalize_schedules(data.get("schedules"), schedule_aliases, time),
        _normalize_device_references(data.get("devices"), device_aliases, time),
    )


def _normalize_scenes(
    rows: object,
    aliases: AliasMap,
    time: ObservationTime,
) -> ParsedCollection[SceneDefinition]:
    if not isinstance(rows, list):
        return ParsedCollection((), Quality.MISSING, time, "scenes_missing")
    items: list[SceneDefinition] = []
    invalid_count = 0
    unmapped_count = 0
    for candidate in rows:
        row = _row(candidate, 8)
        if row is None:
            invalid_count += 1
            continue
        values = tuple(_integer(row[index]) for index in (0, 2, 3, 4, 5, 6))
        if (
            any(value is None for value in values)
            or values[2] is None
            or values[2] < 0
            or values[3] is None
            or not 0 <= values[3] <= 100
            or values[5] is None
            or not 0 <= values[5] <= 0xFFFFFF
        ):
            invalid_count += 1
            continue
        source_id, icon, sort_order, brightness, temperature, rgb = values
        assert None not in values
        target_ref = aliases.get(source_id)
        if target_ref is None:
            unmapped_count += 1
            continue
        items.append(
            SceneDefinition(
                target_ref,
                icon,
                sort_order,
                brightness,
                temperature,
                rgb,
            )
        )
    quality, reason = _collection_quality(
        invalid_count=invalid_count,
        unmapped_count=unmapped_count,
    )
    return ParsedCollection(
        tuple(items), quality, time, reason, invalid_count, unmapped_count
    )


def _normalize_schedules(
    rows: object,
    aliases: AliasMap,
    time: ObservationTime,
) -> ParsedCollection[ScheduleDefinition]:
    if not isinstance(rows, list):
        return ParsedCollection((), Quality.MISSING, time, "schedules_missing")
    items: list[ScheduleDefinition] = []
    invalid_count = 0
    unmapped_count = 0
    for candidate in rows:
        row = _row(candidate, 6)
        if row is None:
            invalid_count += 1
            continue
        source_id = _integer(row[0])
        icon = _integer(row[2])
        active = _integer(row[3])
        sort_order = _integer(row[5])
        workday = row[4]
        if (
            source_id is None
            or icon is None
            or active not in {0, 1}
            or not isinstance(workday, str)
            or sort_order is None
        ):
            invalid_count += 1
            continue
        if sort_order < 0:
            continue
        target_ref = aliases.get(source_id)
        if target_ref is None:
            unmapped_count += 1
            continue
        items.append(
            ScheduleDefinition(
                target_ref,
                icon,
                active == 1,
                workday,
                sort_order,
            )
        )
    quality, reason = _collection_quality(
        invalid_count=invalid_count,
        unmapped_count=unmapped_count,
    )
    return ParsedCollection(
        tuple(items), quality, time, reason, invalid_count, unmapped_count
    )


def _normalize_device_references(
    rows: object,
    aliases: AliasMap,
    time: ObservationTime,
) -> ParsedCollection[DeviceReference]:
    if not isinstance(rows, list):
        return ParsedCollection((), Quality.MISSING, time, "devices_missing")
    items: list[DeviceReference] = []
    invalid_count = 0
    unmapped_count = 0
    for candidate in rows:
        row = _row(candidate, 1)
        source_id = None if row is None else _integer(row[0])
        if source_id is None:
            invalid_count += 1
            continue
        target_ref = aliases.get(source_id)
        if target_ref is None:
            unmapped_count += 1
            continue
        items.append(DeviceReference(target_ref))
    quality, reason = _collection_quality(
        invalid_count=invalid_count,
        unmapped_count=unmapped_count,
    )
    return ParsedCollection(
        tuple(items), quality, time, reason, invalid_count, unmapped_count
    )


def normalize_sensor_list(
    response: object,
    *,
    aliases: AliasMap,
    time: ObservationTime,
) -> ParsedCollection[SensorState]:
    data, quality, reason = _response_data(response, list)
    if data is None:
        return ParsedCollection((), quality, time, reason)
    items: list[SensorState] = []
    invalid_count = 0
    unmapped_count = 0
    for candidate in data:
        row = _row(candidate, 12)
        if row is None:
            invalid_count += 1
            continue
        source_id = _integer(row[0])
        device_type = _integer(row[4])
        special_type = _integer(row[5])
        online_raw = _integer(row[13]) if len(row) > 13 else None
        if (
            source_id is None
            or device_type is None
            or special_type is None
            or online_raw not in {None, 0, 1}
        ):
            invalid_count += 1
            continue
        target_ref = aliases.get(source_id)
        if target_ref is None:
            unmapped_count += 1
            continue
        items.append(
            SensorState(
                target_ref,
                device_type,
                special_type,
                None if online_raw is None else online_raw == 1,
            )
        )
    quality, reason = _collection_quality(
        invalid_count=invalid_count,
        unmapped_count=unmapped_count,
    )
    return ParsedCollection(
        tuple(items), quality, time, reason, invalid_count, unmapped_count
    )


def normalize_illuminance(
    response: object,
    *,
    target_ref: str,
    time: ObservationTime,
) -> IlluminanceReading:
    if not isinstance(response, Mapping):
        return IlluminanceReading(
            target_ref, None, Quality.INVALID, time, "response_not_object"
        )
    code = response.get("ErrorCode")
    if isinstance(code, bool) or not isinstance(code, int):
        return IlluminanceReading(
            target_ref, None, Quality.MISSING, time, "error_code_missing_or_invalid"
        )
    if code != 0:
        return IlluminanceReading(
            target_ref, None, Quality.UNKNOWN, time, "gateway_rejected_request"
        )
    value = _integer(response.get("val"))
    if value is None:
        return IlluminanceReading(
            target_ref, None, Quality.MISSING, time, "illuminance_missing"
        )
    if value == 9999:
        return IlluminanceReading(
            target_ref, None, Quality.MISSING, time, "no_usable_value"
        )
    if value < 0:
        return IlluminanceReading(
            target_ref, None, Quality.INVALID, time, "illuminance_out_of_range"
        )
    return IlluminanceReading(target_ref, value, Quality.GOOD, time)


def normalize_schedule_detail(
    response: object,
    *,
    target_ref: str,
    scene_aliases: AliasMap,
    time: ObservationTime,
) -> ParsedCollection[ScheduleDetail]:
    data, quality, reason = _response_data(response, dict)
    if data is None:
        return ParsedCollection((), quality, time, reason)
    assert isinstance(data, Mapping)
    info = _row(data.get("info"), 5)
    details = data.get("details")
    if info is None or not isinstance(details, list):
        return ParsedCollection((), Quality.MISSING, time, "schedule_detail_missing")
    active = _integer(info[0])
    icon = _integer(info[2])
    sort_order = _integer(info[3])
    workday = info[4]
    if (
        active not in {0, 1}
        or icon is None
        or sort_order is None
        or not isinstance(workday, str)
    ):
        return ParsedCollection((), Quality.INVALID, time, "schedule_info_invalid", 1)

    steps: list[ScheduleStep] = []
    invalid_count = 0
    unmapped_count = 0
    for candidate in details:
        row = _row(candidate, 5)
        if row is None:
            invalid_count += 1
            continue
        step_sort = _integer(row[1])
        seconds = _integer(row[2])
        source_scene_id = _integer(row[3])
        scene_icon = _integer(row[4])
        if (
            step_sort is None
            or seconds is None
            or not 0 <= seconds < 86_400
            or source_scene_id is None
            or scene_icon is None
        ):
            invalid_count += 1
            continue
        scene_ref = scene_aliases.get(source_scene_id)
        if scene_ref is None:
            unmapped_count += 1
            continue
        steps.append(ScheduleStep(step_sort, seconds, scene_ref, scene_icon))
    collection_quality, collection_reason = _collection_quality(
        invalid_count=invalid_count,
        unmapped_count=unmapped_count,
    )
    detail = ScheduleDetail(
        target_ref,
        active == 1,
        icon,
        sort_order,
        workday,
        tuple(steps),
        collection_quality,
    )
    return ParsedCollection(
        (detail,),
        collection_quality,
        time,
        collection_reason,
        invalid_count,
        unmapped_count,
    )
