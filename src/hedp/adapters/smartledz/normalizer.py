"""Normalise already-acquired Smart LEDZ JSON responses without transport."""

from __future__ import annotations

from collections.abc import Mapping
import re

from .models import Quality, ResourceKind, ResourceResponse


_ERROR_CODE = "ErrorCode"
_SENSITIVE_FIELD_PARTS = frozenset(
    {
        "address",
        "auth",
        "config",
        "configuration",
        "cookie",
        "id",
        "ip",
        "mac",
        "name",
        "password",
        "secret",
        "serial",
        "setting",
        "ssid",
        "token",
        "udn",
    }
)


def _is_sensitive_field_name(name: str) -> bool:
    with_word_boundaries = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    normalized = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", with_word_boundaries)
    normalized = normalized.casefold().replace("-", "_")
    parts = tuple(part for part in normalized.split("_") if part)
    return bool(_SENSITIVE_FIELD_PARTS.intersection(parts))


def _unknown_fields(response: Mapping[object, object]) -> tuple[tuple[str, ...], int]:
    names: list[str] = []
    redacted_count = 0

    for key in response:
        if key == _ERROR_CODE:
            continue
        if not isinstance(key, str) or _is_sensitive_field_name(key):
            redacted_count += 1
            continue
        names.append(key)
    return tuple(sorted(names)), redacted_count


def normalize_resource_response(
    resource: ResourceKind, response: object
) -> ResourceResponse:
    """Classify one response without parsing frames, JSON bytes, or network data.

    ``ErrorCode=0`` is the only confirmed successful envelope value.  Values
    in every other field remain deliberately unmapped until an anonymous,
    observed schema establishes their meaning.  The raw response stays owned
    by the caller's collection boundary.
    """

    if not isinstance(response, Mapping):
        return ResourceResponse(
            resource=resource,
            quality=Quality.INVALID,
            reason="response_not_object",
        )

    unknown_fields, redacted_field_count = _unknown_fields(response)
    if _ERROR_CODE not in response:
        return ResourceResponse(
            resource=resource,
            quality=Quality.MISSING,
            reason="error_code_missing",
            unknown_fields=unknown_fields,
            redacted_field_count=redacted_field_count,
        )
    error_code = response[_ERROR_CODE]
    if isinstance(error_code, bool) or not isinstance(error_code, int):
        return ResourceResponse(
            resource=resource,
            quality=Quality.INVALID,
            reason="error_code_invalid_type",
            unknown_fields=unknown_fields,
            redacted_field_count=redacted_field_count,
        )
    if error_code != 0:
        return ResourceResponse(
            resource=resource,
            quality=Quality.UNKNOWN,
            reason="error_code_not_accepted",
            error_code=error_code,
            unknown_fields=unknown_fields,
            redacted_field_count=redacted_field_count,
        )
    return ResourceResponse(
        resource=resource,
        quality=Quality.GOOD,
        error_code=0,
        unknown_fields=unknown_fields,
        redacted_field_count=redacted_field_count,
    )


def normalize_group_response(response: object) -> ResourceResponse:
    return normalize_resource_response(ResourceKind.GROUP, response)


def normalize_scene_response(response: object) -> ResourceResponse:
    return normalize_resource_response(ResourceKind.SCENE, response)


def normalize_schedule_response(response: object) -> ResourceResponse:
    return normalize_resource_response(ResourceKind.SCHEDULE, response)


def normalize_device_response(response: object) -> ResourceResponse:
    return normalize_resource_response(ResourceKind.DEVICE, response)


def normalize_sensor_response(response: object) -> ResourceResponse:
    return normalize_resource_response(ResourceKind.SENSOR, response)
