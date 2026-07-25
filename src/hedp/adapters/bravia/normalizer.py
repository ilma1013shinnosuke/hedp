from __future__ import annotations

from typing import Any, Mapping

from .errors import ApiError, ErrorCategory, classify_error
from .models import (
    AudioOutput,
    AudioReading,
    ContentState,
    PowerReading,
    PowerState,
    Quality,
)


_ENVELOPE_FIELDS = frozenset({"id", "result", "error"})
_PRIVATE_CONTENT_FIELDS = frozenset(
    {"title", "programTitle", "programMediaType", "startDateTime", "durationSec"}
)


def _envelope_unknown(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in _ENVELOPE_FIELDS}


def _first_result_object(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, ApiError | None, str | None]:
    error = classify_error(payload)
    if error is not None:
        return None, error, "api_error"
    result = payload.get("result")
    if not isinstance(result, list):
        return None, ApiError(ErrorCategory.MALFORMED_RESPONSE), "result_not_list"
    if not result:
        return None, None, "result_empty"
    if not isinstance(result[0], dict):
        return None, ApiError(ErrorCategory.MALFORMED_RESPONSE), "result_item_not_object"
    return dict(result[0]), None, None


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def normalize_power(payload: Mapping[str, Any]) -> PowerReading:
    row, error, reason = _first_result_object(payload)
    envelope_unknown = _envelope_unknown(payload)
    if error is not None:
        return PowerReading(
            quality=Quality.MISSING if error.category != ErrorCategory.MALFORMED_RESPONSE else Quality.INVALID,
            reason=reason,
            unknown=envelope_unknown,
            error=error,
        )
    if row is None:
        return PowerReading(
            quality=Quality.MISSING,
            reason=reason,
            unknown=envelope_unknown,
        )

    raw_value = row.get("status")
    row_unknown = {key: value for key, value in row.items() if key != "status"}
    unknown = {**envelope_unknown, "result_fields": row_unknown} if row_unknown else envelope_unknown
    if raw_value == PowerState.ACTIVE.value:
        return PowerReading(PowerState.ACTIVE, Quality.GOOD, unknown=unknown)
    if raw_value == PowerState.STANDBY.value:
        return PowerReading(PowerState.STANDBY, Quality.GOOD, unknown=unknown)
    if raw_value is None:
        return PowerReading(
            quality=Quality.MISSING,
            reason="status_missing",
            unknown=unknown,
        )
    return PowerReading(
        quality=Quality.UNKNOWN if isinstance(raw_value, str) else Quality.INVALID,
        reason="status_unknown" if isinstance(raw_value, str) else "status_invalid_type",
        raw_value=raw_value,
        unknown=unknown,
    )


def normalize_volume(payload: Mapping[str, Any]) -> AudioReading:
    error = classify_error(payload)
    envelope_unknown = _envelope_unknown(payload)
    if error is not None:
        quality = (
            Quality.INVALID
            if error.category == ErrorCategory.MALFORMED_RESPONSE
            else Quality.MISSING
        )
        return AudioReading(quality=quality, reason="api_error", unknown=envelope_unknown, error=error)

    result = payload.get("result")
    if not isinstance(result, list):
        return AudioReading(
            quality=Quality.INVALID,
            reason="result_not_list",
            unknown=envelope_unknown,
            error=ApiError(ErrorCategory.MALFORMED_RESPONSE),
        )
    if not result:
        return AudioReading(
            quality=Quality.MISSING,
            reason="result_empty",
            unknown=envelope_unknown,
        )
    rows = result[0]
    if not isinstance(rows, list):
        return AudioReading(
            quality=Quality.INVALID,
            reason="result_item_not_list",
            unknown=envelope_unknown,
            error=ApiError(ErrorCategory.MALFORMED_RESPONSE),
        )

    outputs: list[AudioOutput] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        reasons: list[str] = []
        target = _text(row.get("target"))
        volume = _integer(row.get("volume"))
        muted = row.get("mute") if isinstance(row.get("mute"), bool) else None
        minimum = _integer(row.get("minVolume"))
        maximum = _integer(row.get("maxVolume"))
        if target is None:
            reasons.append("target_missing_or_invalid")
        if volume is None:
            reasons.append("volume_missing_or_invalid")
        if muted is None:
            reasons.append("mute_missing_or_invalid")
        known = {"target", "volume", "mute", "minVolume", "maxVolume"}
        outputs.append(
            AudioOutput(
                target=target,
                volume=volume,
                muted=muted,
                minimum=minimum,
                maximum=maximum,
                quality=Quality.GOOD if not reasons else Quality.INVALID,
                reasons=tuple(reasons),
                unknown={key: value for key, value in row.items() if key not in known},
            )
        )

    if not outputs:
        return AudioReading(
            quality=Quality.MISSING,
            reason="no_object_outputs",
            unknown=envelope_unknown,
        )
    quality = Quality.GOOD if all(item.quality == Quality.GOOD for item in outputs) else Quality.INVALID
    return AudioReading(tuple(outputs), quality, unknown=envelope_unknown)


def normalize_content(payload: Mapping[str, Any]) -> ContentState:
    row, error, reason = _first_result_object(payload)
    envelope_unknown = _envelope_unknown(payload)
    if error is not None:
        quality = (
            Quality.INVALID
            if error.category == ErrorCategory.MALFORMED_RESPONSE
            else Quality.MISSING
        )
        return ContentState(
            quality=quality,
            reason=reason,
            unknown=envelope_unknown,
            error=error,
        )
    if row is None:
        return ContentState(
            quality=Quality.MISSING,
            reason=reason,
            unknown=envelope_unknown,
        )

    source = _text(row.get("source"))
    uri = _text(row.get("uri"))
    channel = _text(row.get("dispNum"))
    known = {"source", "uri", "dispNum"} | _PRIVATE_CONTENT_FIELDS
    row_unknown = {key: value for key, value in row.items() if key not in known}
    unknown = {**envelope_unknown, "result_fields": row_unknown} if row_unknown else envelope_unknown
    omitted = tuple(sorted(key for key in _PRIVATE_CONTENT_FIELDS if key in row))

    if source is None and uri is None and channel is None:
        return ContentState(
            quality=Quality.MISSING,
            reason="content_fields_missing",
            omitted_private_fields=omitted,
            unknown=unknown,
        )
    return ContentState(
        source=source,
        uri=uri,
        channel=channel,
        quality=Quality.GOOD,
        omitted_private_fields=omitted,
        unknown=unknown,
    )
