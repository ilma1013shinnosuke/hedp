from __future__ import annotations

import json
from pathlib import Path

import pytest

from hedp.adapters.smartledz import (
    Quality,
    ReadBatch,
    ResourceKind,
    normalize_group_response,
    normalize_read_batch,
    normalize_resource_response,
)


FIXTURES = Path(__file__).parent / "fixtures" / "smartledz"


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_normalizes_already_acquired_resource_envelopes_without_parsing_unknown_schema() -> None:
    batch = ReadBatch(
        group_response=_fixture("group_response_v1.json"),
        scene_response=_fixture("scene_response_v1.json"),
        schedule_response=_fixture("schedule_response_v1.json"),
        device_response=_fixture("device_response_v1.json"),
        sensor_response=_fixture("sensor_response_v1.json"),
        observed_at="2026-07-25T10:00:00+09:00",
        received_at="2026-07-25T10:00:01+09:00",
    )

    reading = normalize_read_batch(batch)

    assert [response.resource for response in (
        reading.groups,
        reading.scenes,
        reading.schedules,
        reading.devices,
        reading.sensors,
    )] == list(ResourceKind)
    assert all(
        response.quality == Quality.GOOD
        and response.error_code == 0
        and response.unknown_fields[0] == "Data"
        and response.unknown_fields[-1] == "futureEnvelope"
        for response in (
            reading.groups,
            reading.scenes,
            reading.schedules,
            reading.devices,
            reading.sensors,
        )
    )
    assert reading.groups.unknown_fields == (
        "Data",
        "futureEnvelope",
    )
    assert reading.observed_at == "2026-07-25T10:00:00+09:00"
    assert reading.received_at == "2026-07-25T10:00:01+09:00"


@pytest.mark.parametrize(
    ("response", "quality", "reason", "error_code"),
    [
        ({}, Quality.MISSING, "error_code_missing", None),
        ({"ErrorCode": None}, Quality.INVALID, "error_code_invalid_type", None),
        ({"ErrorCode": False}, Quality.INVALID, "error_code_invalid_type", None),
        ({"ErrorCode": "0"}, Quality.INVALID, "error_code_invalid_type", None),
        ({"ErrorCode": 4}, Quality.UNKNOWN, "error_code_not_accepted", 4),
        ([], Quality.INVALID, "response_not_object", None),
    ],
)
def test_missing_invalid_and_nonaccepted_responses_remain_distinct(
    response: object,
    quality: Quality,
    reason: str,
    error_code: int | None,
) -> None:
    normalized = normalize_group_response(response)

    assert normalized.resource == ResourceKind.GROUP
    assert normalized.quality == quality
    assert normalized.reason == reason
    assert normalized.error_code == error_code


def test_unknown_values_are_not_retained_and_sensitive_field_names_are_redacted() -> None:
    response = {
        "ErrorCode": 0,
        "futureState": {"value": "not-retained"},
        "DeviceName": "not-retained",
        "GatewayIpAddress": "not-retained",
        "authToken": "not-retained",
    }

    normalized = normalize_resource_response(ResourceKind.DEVICE, response)

    assert normalized.quality == Quality.GOOD
    assert normalized.unknown_fields == ("futureState",)
    assert normalized.redacted_field_count == 3
    assert "not-retained" not in repr(normalized)


def test_fixture_data_is_anonymous_and_contains_no_sensitive_schema_keys() -> None:
    forbidden = {
        "address",
        "auth",
        "cookie",
        "ip",
        "mac",
        "name",
        "password",
        "secret",
        "serial",
        "ssid",
        "token",
        "udn",
    }
    for path in FIXTURES.glob("*.json"):
        payload = _fixture(path.name)
        assert not forbidden.intersection(_all_keys(payload))
        assert "192.168." not in path.read_text(encoding="utf-8")


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for nested in value.values():
            keys.update(_all_keys(nested))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for nested in value:
            keys.update(_all_keys(nested))
        return keys
    return set()
