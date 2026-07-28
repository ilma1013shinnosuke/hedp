"""Pure comparison evidence for existing Collector and KURA-delivered Raw."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any


PROTOCOL_VERSION = "kura.shadow-comparison/1"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = (
    "app_id",
    "source_id",
    "raw_sha256",
    "raw_size",
    "retrieved_at",
    "checked_at",
    "formatted_sha256",
    "formatted_item_count",
)


def build_shadow_observation(
    *,
    app_id: str,
    source_id: str,
    raw: bytes,
    retrieved_at: datetime,
    checked_at: datetime,
    formatted_records: Sequence[object],
) -> dict[str, object]:
    """Build deterministic comparison evidence from app-owned outputs."""

    formatted = json.dumps(
        formatted_records,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return {
        "app_id": app_id,
        "source_id": source_id,
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_size": len(raw),
        "retrieved_at": _render_time(retrieved_at),
        "checked_at": _render_time(checked_at),
        "formatted_sha256": hashlib.sha256(formatted).hexdigest(),
        "formatted_item_count": len(formatted_records),
    }


def compare_shadow(
    baseline: Mapping[str, object],
    candidate: Mapping[str, object],
) -> dict[str, Any]:
    """Compare two observations without interpreting or repairing content."""

    validators: dict[str, Callable[[object], object | None]] = {
        "app_id": _identifier,
        "source_id": _identifier,
        "raw_sha256": _sha256,
        "raw_size": _non_negative_integer,
        "retrieved_at": _timestamp,
        "checked_at": _timestamp,
        "formatted_sha256": _sha256,
        "formatted_item_count": _non_negative_integer,
    }
    differences: list[dict[str, object]] = []
    normalized: dict[str, dict[str, object]] = {"baseline": {}, "candidate": {}}
    comparable = True

    for field, validator in validators.items():
        raw_values = {
            "baseline": baseline.get(field),
            "candidate": candidate.get(field),
        }
        field_valid = True
        for side, observation in (("baseline", baseline), ("candidate", candidate)):
            if field not in observation:
                comparable = False
                field_valid = False
                differences.append(
                    {
                        "field": field,
                        "reason": f"{side}_missing_field",
                        "baseline": raw_values["baseline"],
                        "candidate": raw_values["candidate"],
                    }
                )
                continue
            value = validator(raw_values[side])
            if value is None:
                comparable = False
                field_valid = False
                differences.append(
                    {
                        "field": field,
                        "reason": f"{side}_invalid_value",
                        "baseline": raw_values["baseline"],
                        "candidate": raw_values["candidate"],
                    }
                )
                continue
            normalized[side][field] = value
        if (
            field_valid
            and normalized["baseline"][field] != normalized["candidate"][field]
        ):
            differences.append(
                {
                    "field": field,
                    "reason": f"{field}_mismatch",
                    "baseline": raw_values["baseline"],
                    "candidate": raw_values["candidate"],
                }
            )

    status = "incomparable" if not comparable else ("mismatch" if differences else "match")
    return {
        "protocol_version": PROTOCOL_VERSION,
        "status": status,
        "baseline_app_id": baseline.get("app_id"),
        "candidate_app_id": candidate.get("app_id"),
        "source_id": (
            baseline.get("source_id")
            if baseline.get("source_id") == candidate.get("source_id")
            else None
        ),
        "compared_fields": list(_FIELDS),
        "differences": differences,
    }


def _render_time(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("shadow timestamps must include a UTC offset")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _identifier(value: object) -> str | None:
    return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else None


def _sha256(value: object) -> str | None:
    return value if isinstance(value, str) and _SHA256.fullmatch(value) else None


def _non_negative_integer(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _timestamp(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return _render_time(parsed)
