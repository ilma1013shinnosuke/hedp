from __future__ import annotations

import json
from pathlib import Path

import pytest

from hedp.adapters.smartledz import (
    Quality,
    SENSOR_TYPE_CODES,
    ObservationTime,
    device_get,
    device_list,
    group_get,
    group_list,
    normalize_group_detail,
    normalize_group_list,
    normalize_illuminance,
    normalize_schedule_detail,
    normalize_sensor_list,
    schedule_get,
    sensor_lux,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "smartledz"
    / "confirmed_read_resources_v1.json"
)
TIME = ObservationTime(
    "2026-07-25T10:00:00+09:00",
    "2026-07-25T10:00:01+09:00",
)


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_confirmed_read_commands_are_exact_and_hide_identifiers_from_repr() -> None:
    commands = (
        group_list(gateway_id=11),
        group_get(gateway_id=11, group_id=101),
        device_list(gateway_id=11, group_id=101),
        device_get(gateway_id=11, device_id=401),
        schedule_get(gateway_id=11, group_id=101, schedule_id=301),
        sensor_lux(gateway_id=11, destination=501),
    )

    assert [command.command for command in commands] == [
        "GroupList",
        "GroupGet",
        "DeviceList",
        "DeviceGet",
        "GroupScheduleGet",
        "DeviceSensorSwitchGetLuxValues",
    ]
    assert commands[2].payload()["type_codes"] == list(SENSOR_TYPE_CODES)
    assert commands[4].payload() == {
        "c": "GroupScheduleGet",
        "gateway_id": 11,
        "schedule_id": 301,
        "group_id": 101,
    }
    assert "101" not in repr(commands[1])
    assert "401" not in repr(commands[3])


def test_normalizes_confirmed_read_resources_with_runtime_aliases() -> None:
    fixture = _fixture()
    groups = normalize_group_list(
        fixture["group_list"],
        aliases={101: "group-primary"},
        time=TIME,
    )
    detail = normalize_group_detail(
        fixture["group_detail"],
        scene_aliases={201: "scene-default"},
        schedule_aliases={301: "schedule-weekday"},
        device_aliases={401: "light-primary"},
        time=TIME,
    )
    sensors = normalize_sensor_list(
        fixture["sensor_list"],
        aliases={501: "sensor-primary"},
        time=TIME,
    )
    lux = normalize_illuminance(
        fixture["illuminance"],
        target_ref="sensor-primary",
        time=TIME,
    )
    schedule = normalize_schedule_detail(
        fixture["schedule_detail"],
        target_ref="schedule-weekday",
        scene_aliases={201: "scene-default"},
        time=TIME,
    )

    assert groups.quality == Quality.GOOD
    assert groups.items[0].power is True
    assert groups.items[0].brightness_pct == 64
    assert detail.scenes.items[0].color_temperature_100k == 30
    assert detail.schedules.items[0].active is True
    assert detail.devices.quality == Quality.GOOD
    assert sensors.items[0].online is True
    assert lux.illuminance == 420
    assert schedule.items[0].steps[0].sort_order == 0
    assert TIME.observed_at == groups.time.observed_at


def test_unmapped_household_identifiers_do_not_cross_reader_boundary() -> None:
    fixture = _fixture()
    groups = normalize_group_list(fixture["group_list"], aliases={}, time=TIME)

    assert groups.items == ()
    assert groups.quality == Quality.UNKNOWN
    assert groups.reason == "target_alias_missing"
    assert groups.unmapped_count == 1
    assert "101" not in repr(groups)
    assert "anonymous" not in repr(groups)


def test_invalid_rows_and_no_value_sentinel_have_explicit_quality() -> None:
    groups = normalize_group_list(
        {"ErrorCode": 0, "data": [[101, "anonymous", 1]]},
        aliases={101: "group-primary"},
        time=TIME,
    )
    lux = normalize_illuminance(
        {"ErrorCode": 0, "val": 9999},
        target_ref="sensor-primary",
        time=TIME,
    )

    assert groups.quality == Quality.INVALID
    assert groups.invalid_count == 1
    assert lux.quality == Quality.MISSING
    assert lux.reason == "no_usable_value"


@pytest.mark.parametrize(
    ("response", "quality"),
    [
        ({}, Quality.MISSING),
        ({"ErrorCode": 7}, Quality.UNKNOWN),
        ({"ErrorCode": 0}, Quality.MISSING),
        ([], Quality.INVALID),
    ],
)
def test_envelope_failures_are_not_success(
    response: object,
    quality: Quality,
) -> None:
    result = normalize_group_list(response, aliases={}, time=TIME)

    assert result.quality == quality
    assert result.items == ()


def test_timestamps_require_timezone_and_monotonic_receipt() -> None:
    with pytest.raises(ValueError, match="UTC offset"):
        ObservationTime("2026-07-25T10:00:00", "2026-07-25T10:00:01")
    with pytest.raises(ValueError, match="earlier"):
        ObservationTime(
            "2026-07-25T10:00:02+09:00",
            "2026-07-25T10:00:01+09:00",
        )


def test_fixture_is_anonymous_and_contains_no_network_or_authentication_data() -> None:
    text = FIXTURE.read_text(encoding="utf-8").casefold()

    for forbidden in (
        "192.168.",
        "password",
        "token",
        "cookie",
        "ssid",
        "serial",
        "gateway_id",
        "device_id",
        "group_id",
    ):
        assert forbidden not in text
