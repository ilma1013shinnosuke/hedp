"""Typed normalization for SwitchBot robot-vacuum status responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from hedp.observations import Quality


class RobotWorkingStatus(str, Enum):
    STANDBY = "standby"
    CLEANING = "cleaning"
    PAUSED = "paused"
    RETURNING_TO_DOCK = "returning_to_dock"
    CHARGING = "charging"
    CHARGE_DONE = "charge_done"
    DORMANT = "dormant"
    TROUBLE = "trouble"
    REMOTE_CONTROL = "remote_control"
    DUST_COLLECTING = "dust_collecting"
    UNKNOWN = "unknown"


class RobotChargingStatus(str, Enum):
    NOT_CHARGING = "not_charging"
    RETURNING_TO_DOCK = "returning_to_dock"
    CHARGING = "charging"
    CHARGED = "charged"
    UNKNOWN = "unknown"


class RobotTaskStatus(str, Enum):
    STANDBY = "standby"
    EXPLORE = "explore"
    CLEAN_ALL = "clean_all"
    CLEAN_AREA = "clean_area"
    CLEAN_ROOM = "clean_room"
    FILL_WATER = "fill_water"
    DEEP_WASHING = "deep_washing"
    BACK_TO_CHARGE = "back_to_charge"
    MARKING_WATER_BASE = "marking_water_base"
    DRYING = "drying"
    COLLECT_DUST = "collect_dust"
    REMOTE_CONTROL = "remote_control"
    CLEAN_WITH_EXPLORER = "clean_with_explorer"
    FILL_WATER_FOR_HUMIDIFIER = "fill_water_for_humidifier"
    MARKING_HUMIDIFIER = "marking_humidifier"
    NONE = "none"
    UNKNOWN = "unknown"


_WORKING_STATUSES = {
    "standby": RobotWorkingStatus.STANDBY,
    "clearing": RobotWorkingStatus.CLEANING,
    "paused": RobotWorkingStatus.PAUSED,
    "gotochargebase": RobotWorkingStatus.RETURNING_TO_DOCK,
    "charging": RobotWorkingStatus.CHARGING,
    "chargedone": RobotWorkingStatus.CHARGE_DONE,
    "dormant": RobotWorkingStatus.DORMANT,
    "introuble": RobotWorkingStatus.TROUBLE,
    "inremotecontrol": RobotWorkingStatus.REMOTE_CONTROL,
    "industcollecting": RobotWorkingStatus.DUST_COLLECTING,
}

_TASK_STATUSES = {
    "standby": RobotTaskStatus.STANDBY,
    "explore": RobotTaskStatus.EXPLORE,
    "cleanall": RobotTaskStatus.CLEAN_ALL,
    "cleanarea": RobotTaskStatus.CLEAN_AREA,
    "cleanroom": RobotTaskStatus.CLEAN_ROOM,
    "fillwater": RobotTaskStatus.FILL_WATER,
    "deepwashing": RobotTaskStatus.DEEP_WASHING,
    "backtocharge": RobotTaskStatus.BACK_TO_CHARGE,
    "markingwaterbase": RobotTaskStatus.MARKING_WATER_BASE,
    "drying": RobotTaskStatus.DRYING,
    "collectdust": RobotTaskStatus.COLLECT_DUST,
    "remotecontrol": RobotTaskStatus.REMOTE_CONTROL,
    "cleanwithexplorer": RobotTaskStatus.CLEAN_WITH_EXPLORER,
    "fillwaterforhumi": RobotTaskStatus.FILL_WATER_FOR_HUMIDIFIER,
    "markinghumi": RobotTaskStatus.MARKING_HUMIDIFIER,
}


@dataclass(frozen=True)
class RobotState:
    battery_percent: int | None
    working_status: RobotWorkingStatus
    charging_status: RobotChargingStatus
    task_status: RobotTaskStatus
    online: bool | None
    observed_at: datetime
    unknown_values: tuple[str, ...] = field(default=(), repr=False)
    water_base_battery_percent: int | None = None
    quality: Quality = Quality.GOOD

    def __post_init__(self) -> None:
        if not isinstance(self.working_status, RobotWorkingStatus):
            raise TypeError("working_status must be RobotWorkingStatus")
        if not isinstance(self.charging_status, RobotChargingStatus):
            raise TypeError("charging_status must be RobotChargingStatus")
        if not isinstance(self.task_status, RobotTaskStatus):
            raise TypeError("task_status must be RobotTaskStatus")
        if self.battery_percent is not None and (
            isinstance(self.battery_percent, bool)
            or not isinstance(self.battery_percent, int)
            or not 0 <= self.battery_percent <= 100
        ):
            raise ValueError("battery_percent must be an integer from 0 to 100")
        if self.online is not None and not isinstance(self.online, bool):
            raise TypeError("online must be a boolean or None")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.water_base_battery_percent is not None and (
            isinstance(self.water_base_battery_percent, bool)
            or not isinstance(self.water_base_battery_percent, int)
            or not 0 <= self.water_base_battery_percent <= 100
        ):
            raise ValueError(
                "water_base_battery_percent must be an integer from 0 to 100"
            )
        if not isinstance(self.quality, Quality):
            raise TypeError("quality must be Quality")


def normalize_robot_state(body: dict[str, Any], *, observed_at: datetime) -> RobotState:
    """Normalize the official status vocabulary without guessing new values."""

    raw_working = body.get("workingStatus")
    working = (
        _WORKING_STATUSES.get(raw_working.strip().casefold())
        if isinstance(raw_working, str)
        else None
    )
    raw_task = body.get("taskType")
    if raw_task is None:
        task = RobotTaskStatus.NONE
    elif isinstance(raw_task, str):
        task = _TASK_STATUSES.get(raw_task.strip().casefold())
    else:
        task = None

    unknown_values = []
    if raw_working is not None and working is None:
        unknown_values.append("workingStatus")
    if raw_task is not None and task is None:
        unknown_values.append("taskType")

    battery = body.get("battery")
    if (
        isinstance(battery, bool)
        or not isinstance(battery, int)
        or not 0 <= battery <= 100
    ):
        battery = None

    water_base_battery = body.get("waterBaseBattery")
    if water_base_battery is not None and (
        isinstance(water_base_battery, bool)
        or not isinstance(water_base_battery, int)
        or not 0 <= water_base_battery <= 100
    ):
        water_base_battery = None
        unknown_values.append("waterBaseBattery")

    online_value = body.get("onlineStatus")
    online = (
        True
        if online_value == "online"
        else False
        if online_value == "offline"
        else None
    )
    normalized_working = working or RobotWorkingStatus.UNKNOWN
    return RobotState(
        battery_percent=battery,
        working_status=normalized_working,
        charging_status=_charging_status(normalized_working),
        task_status=task or RobotTaskStatus.UNKNOWN,
        online=online,
        observed_at=observed_at,
        unknown_values=tuple(unknown_values),
        water_base_battery_percent=water_base_battery,
        quality=(
            Quality.UNKNOWN
            if normalized_working is RobotWorkingStatus.UNKNOWN
            else Quality.GOOD
        ),
    )


def _charging_status(
    working_status: RobotWorkingStatus,
) -> RobotChargingStatus:
    if working_status is RobotWorkingStatus.RETURNING_TO_DOCK:
        return RobotChargingStatus.RETURNING_TO_DOCK
    if working_status is RobotWorkingStatus.CHARGING:
        return RobotChargingStatus.CHARGING
    if working_status is RobotWorkingStatus.CHARGE_DONE:
        return RobotChargingStatus.CHARGED
    if working_status is RobotWorkingStatus.UNKNOWN:
        return RobotChargingStatus.UNKNOWN
    return RobotChargingStatus.NOT_CHARGING
