"""Privacy-safe orchestration of confirmed Smart LEDZ read commands."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Callable, Protocol

from hedp.observations import ObservationTime
from hedp.storage import RawData

from .read_commands import (
    ReadCommand,
    device_list,
    group_get,
    group_list,
    schedule_get,
    sensor_lux,
)
from .state import (
    GroupDetail,
    ParsedCollection,
    normalize_group_detail,
    normalize_group_list,
    normalize_illuminance,
    normalize_schedule_detail,
    normalize_sensor_list,
)


class SmartLedzReadPort(Protocol):
    """A transport boundary that accepts confirmed read commands only."""

    def read(self, command: ReadCommand) -> object: ...


@dataclass(frozen=True)
class SmartLedzReadTargets:
    gateway_id: int = field(repr=False)
    group_aliases: Mapping[int, str] = field(repr=False)
    scene_aliases: Mapping[int, str] = field(repr=False)
    schedule_aliases: Mapping[int, str] = field(repr=False)
    device_aliases: Mapping[int, str] = field(repr=False)
    sensor_aliases: Mapping[int, str] = field(repr=False)
    schedule_groups: Mapping[int, int] = field(repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.gateway_id, bool) or not isinstance(self.gateway_id, int):
            raise TypeError("gateway_id must be an integer")
        if not 0 <= self.gateway_id <= 0xFFFF:
            raise ValueError("gateway_id is out of range")
        for name, aliases in (
            ("group", self.group_aliases),
            ("scene", self.scene_aliases),
            ("schedule", self.schedule_aliases),
            ("device", self.device_aliases),
            ("sensor", self.sensor_aliases),
        ):
            if any(
                isinstance(source_id, bool)
                or not isinstance(source_id, int)
                or not 0 <= source_id <= 0xFFFF
                or not isinstance(target_ref, str)
                or not target_ref
                for source_id, target_ref in aliases.items()
            ):
                raise ValueError(f"{name} aliases are invalid")
        if any(
            isinstance(schedule_id, bool)
            or not isinstance(schedule_id, int)
            or isinstance(group_id, bool)
            or not isinstance(group_id, int)
            for schedule_id, group_id in self.schedule_groups.items()
        ):
            raise ValueError("schedule groups are invalid")
        if set(self.schedule_groups).difference(self.schedule_aliases):
            raise ValueError("schedule group has no configured schedule alias")
        if set(self.schedule_groups.values()).difference(self.group_aliases):
            raise ValueError("schedule group has no configured group alias")


class SmartLedzReadOnlyCollector:
    source = "smartledz_read_only"

    def __init__(
        self,
        transport: SmartLedzReadPort,
        targets: SmartLedzReadTargets,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._transport = transport
        self._targets = targets
        self._clock = clock

    def collect(self) -> RawData:
        received_at = self._clock()
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        time = ObservationTime(received_at.isoformat(), received_at.isoformat())
        evidence: list[str] = []

        groups_response = self._read(
            group_list(gateway_id=self._targets.gateway_id),
            evidence,
        )
        groups = normalize_group_list(
            groups_response,
            aliases=self._targets.group_aliases,
            time=time,
        )

        details: list[dict[str, object]] = []
        sensors: list[dict[str, object]] = []
        for source_group_id, target_ref in self._targets.group_aliases.items():
            detail_response = self._read(
                group_get(
                    gateway_id=self._targets.gateway_id,
                    group_id=source_group_id,
                ),
                evidence,
            )
            detail = normalize_group_detail(
                detail_response,
                scene_aliases=self._targets.scene_aliases,
                schedule_aliases=self._targets.schedule_aliases,
                device_aliases=self._targets.device_aliases,
                time=time,
            )
            details.append({"target_ref": target_ref, **_group_detail(detail)})

            sensor_response = self._read(
                device_list(
                    gateway_id=self._targets.gateway_id,
                    group_id=source_group_id,
                ),
                evidence,
            )
            sensor_collection = normalize_sensor_list(
                sensor_response,
                aliases=self._targets.sensor_aliases,
                time=time,
            )
            sensors.append(
                {
                    "group_ref": target_ref,
                    **_collection(sensor_collection, _sensor),
                }
            )

        schedules: list[dict[str, object]] = []
        for schedule_id, group_id in self._targets.schedule_groups.items():
            response = self._read(
                schedule_get(
                    gateway_id=self._targets.gateway_id,
                    group_id=group_id,
                    schedule_id=schedule_id,
                ),
                evidence,
            )
            collection = normalize_schedule_detail(
                response,
                target_ref=self._targets.schedule_aliases[schedule_id],
                scene_aliases=self._targets.scene_aliases,
                time=time,
            )
            schedules.append(_collection(collection, _schedule_detail))

        illuminance: list[dict[str, object]] = []
        for sensor_id, target_ref in self._targets.sensor_aliases.items():
            response = self._read(
                sensor_lux(
                    gateway_id=self._targets.gateway_id,
                    destination=sensor_id,
                ),
                evidence,
            )
            reading = normalize_illuminance(
                response,
                target_ref=target_ref,
                time=time,
            )
            illuminance.append(
                {
                    "target_ref": target_ref,
                    "value": reading.illuminance,
                    "quality": reading.quality.value,
                    "reason": reading.reason,
                    "observed_at": reading.time.observed_at,
                    "received_at": reading.time.received_at,
                }
            )

        return RawData(
            source=self.source,
            timestamp=received_at,
            payload={
                "groups": _collection(groups, _group),
                "group_details": details,
                "sensors": sensors,
                "schedules": schedules,
                "illuminance": illuminance,
                "evidence_sha256": evidence,
            },
            metadata={
                "timestamp_basis": "collector_receipt",
                "raw_policy": "fingerprint_only_due_to_household_secrets",
                "group_count": len(self._targets.group_aliases),
                "sensor_count": len(self._targets.sensor_aliases),
                "schedule_count": len(self._targets.schedule_groups),
            },
        )

    def _read(self, command: ReadCommand, evidence: list[str]) -> object:
        response = self._transport.read(command)
        evidence.append(_fingerprint(response))
        return response


def _collection(
    value: ParsedCollection[object],
    serialize: Callable[[object], dict[str, object]],
) -> dict[str, object]:
    return {
        "quality": value.quality.value,
        "reason": value.reason,
        "invalid_count": value.invalid_count,
        "unmapped_count": value.unmapped_count,
        "observed_at": value.time.observed_at,
        "received_at": value.time.received_at,
        "items": [serialize(item) for item in value.items],
    }


def _group(value: object) -> dict[str, object]:
    return {
        "target_ref": value.target_ref,
        "power": value.power,
        "brightness_pct": value.brightness_pct,
        "fade_time": value.fade_time,
        "quality": value.quality.value,
    }


def _scene(value: object) -> dict[str, object]:
    return {
        "target_ref": value.target_ref,
        "icon": value.icon,
        "sort_order": value.sort_order,
        "brightness_pct": value.brightness_pct,
        "color_temperature_100k": value.color_temperature_100k,
        "rgb": value.rgb,
        "quality": value.quality.value,
    }


def _schedule(value: object) -> dict[str, object]:
    return {
        "target_ref": value.target_ref,
        "icon": value.icon,
        "active": value.active,
        "workday_mask": value.workday_mask,
        "sort_order": value.sort_order,
        "quality": value.quality.value,
    }


def _device(value: object) -> dict[str, object]:
    return {
        "target_ref": value.target_ref,
        "quality": value.quality.value,
    }


def _sensor(value: object) -> dict[str, object]:
    return {
        "target_ref": value.target_ref,
        "device_type": value.device_type,
        "special_type_code": value.special_type_code,
        "online": value.online,
        "quality": value.quality.value,
    }


def _group_detail(value: GroupDetail) -> dict[str, object]:
    return {
        "scenes": _collection(value.scenes, _scene),
        "schedules": _collection(value.schedules, _schedule),
        "devices": _collection(value.devices, _device),
    }


def _schedule_detail(value: object) -> dict[str, object]:
    return {
        "target_ref": value.target_ref,
        "active": value.active,
        "icon": value.icon,
        "sort_order": value.sort_order,
        "workday_mask": value.workday_mask,
        "quality": value.quality.value,
        "steps": [
            {
                "sort_order": step.sort_order,
                "seconds_from_midnight": step.seconds_from_midnight,
                "scene_ref": step.scene_ref,
                "scene_icon": step.scene_icon,
            }
            for step in value.steps
        ],
    }


def _fingerprint(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(canonical).hexdigest()
