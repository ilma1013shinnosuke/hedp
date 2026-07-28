"""Language-independent validation for the ``kura.delivery/1`` boundary.

This module intentionally has no dependency on KURA code, services, or storage.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping, cast


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ReceiverPolicy:
    recipient: str
    allowed_purposes: frozenset[str]
    allowed_source_ids: frozenset[str]
    allowed_connector_release_ids: frozenset[str]
    allowed_media_types: frozenset[str] = frozenset({"application/pdf"})


@dataclass(frozen=True)
class DeliveryCommitRecord:
    recipient: str
    envelope_sha256: str
    raw_sha256: str
    raw_size: int


@dataclass(frozen=True)
class ConformanceResult:
    accepted: bool
    code: str
    delivery_id: str | None
    duplicate: bool = False
    requires_commit: bool = False
    requires_ack: bool = False
    commit_record: DeliveryCommitRecord | None = None


class InvalidDeliveryJson(ValueError):
    """The untrusted delivery document is not safe JSON."""


def parse_delivery_json(value: bytes | str) -> dict[str, Any]:
    """Parse UTF-8 JSON and reject duplicate keys at every object depth."""

    if isinstance(value, bytes):
        try:
            text = value.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise InvalidDeliveryJson("delivery JSON is not valid UTF-8") from error
    elif isinstance(value, str):
        text = value
    else:
        raise InvalidDeliveryJson("delivery JSON must be UTF-8 bytes or text")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise InvalidDeliveryJson(f"duplicate JSON key: {key}")
            result[key] = item
        return result

    try:
        parsed = json.loads(text, object_pairs_hook=unique_object)
    except (json.JSONDecodeError, TypeError) as error:
        raise InvalidDeliveryJson("delivery JSON is invalid") from error
    if not isinstance(parsed, dict):
        raise InvalidDeliveryJson("delivery JSON top level must be an object")
    return parsed


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """Return the exact canonical representation required by KURA v1."""

    text = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (text + "\n").encode("utf-8")


def canonical_envelope_sha256(envelope: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(envelope)).hexdigest()


def validate_delivery_json(
    envelope_json: bytes | str,
    raw: bytes,
    envelope_sha256: str,
    policy: ReceiverPolicy,
    *,
    committed_delivery_records: Mapping[str, DeliveryCommitRecord] | None = None,
    now: datetime | None = None,
) -> ConformanceResult:
    """Validate an untrusted delivery without consulting KURA state."""

    try:
        envelope = parse_delivery_json(envelope_json)
    except InvalidDeliveryJson:
        return _reject("INVALID_ENVELOPE", None)
    return validate_delivery(
        envelope,
        raw,
        envelope_sha256,
        policy,
        committed_delivery_records=committed_delivery_records,
        now=now,
    )


def validate_delivery(
    envelope: Mapping[str, Any],
    raw: bytes,
    envelope_sha256: str,
    policy: ReceiverPolicy,
    *,
    committed_delivery_records: Mapping[str, DeliveryCommitRecord] | None = None,
    now: datetime | None = None,
) -> ConformanceResult:
    """Apply the KURA Receiver Conformance v1 checks in contract order."""

    delivery_id = _delivery_id(envelope)
    if not _has_valid_structure(envelope):
        return _reject("INVALID_ENVELOPE", delivery_id)
    if not _SHA256_RE.fullmatch(envelope_sha256):
        return _reject("INVALID_ENVELOPE", delivery_id)
    try:
        calculated_envelope_sha256 = canonical_envelope_sha256(envelope)
    except (TypeError, ValueError):
        return _reject("INVALID_ENVELOPE", delivery_id)
    if calculated_envelope_sha256 != envelope_sha256:
        return _reject("ENVELOPE_HASH_MISMATCH", delivery_id)
    if envelope.get("protocol_version") != "kura.delivery/1":
        return _reject("UNSUPPORTED_PROTOCOL", delivery_id)

    delivery = cast(Mapping[str, Any], envelope["delivery"])
    source = cast(Mapping[str, Any], envelope["source"])
    connector = cast(Mapping[str, Any], envelope["connector"])
    artifact = cast(Mapping[str, Any], envelope["artifact"])
    delivery_id = cast(str, delivery["id"])

    if delivery.get("recipient") != policy.recipient:
        return _reject("RECIPIENT_MISMATCH", delivery_id)
    if delivery.get("purpose") not in policy.allowed_purposes:
        return _reject("PURPOSE_MISMATCH", delivery_id)

    expires_at = cast(datetime, _parse_timestamp(delivery["expires_at"]))
    checked_at = now or datetime.now(UTC)
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        return _reject("INVALID_EVALUATION_TIME", delivery_id)
    if expires_at <= checked_at.astimezone(UTC):
        return _reject("DELIVERY_EXPIRED", delivery_id)
    if source.get("id") not in policy.allowed_source_ids:
        return _reject("SOURCE_NOT_ALLOWED", delivery_id)
    if connector.get("release_id") not in policy.allowed_connector_release_ids:
        return _reject("CONNECTOR_NOT_ALLOWED", delivery_id)
    if artifact.get("media_type") not in policy.allowed_media_types:
        return _reject("MEDIA_TYPE_NOT_ALLOWED", delivery_id)

    raw_size = cast(int, artifact["raw_size"])
    if len(raw) != raw_size:
        return _reject("RAW_SIZE_MISMATCH", delivery_id)
    raw_sha256 = cast(str, artifact["sha256"])
    if hashlib.sha256(raw).hexdigest() != raw_sha256:
        return _reject("RAW_HASH_MISMATCH", delivery_id)

    commit_record = DeliveryCommitRecord(
        recipient=cast(str, delivery["recipient"]),
        envelope_sha256=envelope_sha256,
        raw_sha256=raw_sha256,
        raw_size=raw_size,
    )
    previous_record = (committed_delivery_records or {}).get(delivery_id)
    if previous_record == commit_record:
        return ConformanceResult(
            accepted=False,
            code="DUPLICATE_DELIVERY",
            delivery_id=delivery_id,
            duplicate=True,
            commit_record=commit_record,
        )
    if previous_record is not None:
        return ConformanceResult(
            accepted=False,
            code="DELIVERY_ID_CONFLICT",
            delivery_id=delivery_id,
            commit_record=commit_record,
        )
    return ConformanceResult(
        accepted=True,
        code="ACCEPTED",
        delivery_id=delivery_id,
        requires_commit=True,
        requires_ack=True,
        commit_record=commit_record,
    )


def _has_valid_structure(envelope: Mapping[str, Any]) -> bool:
    if not isinstance(envelope.get("protocol_version"), str):
        return False
    delivery = envelope.get("delivery")
    source = envelope.get("source")
    connector = envelope.get("connector")
    collection = envelope.get("collection")
    receipt = envelope.get("receipt")
    artifact = envelope.get("artifact")
    if not all(
        isinstance(value, Mapping)
        for value in (delivery, source, connector, collection, receipt, artifact)
    ):
        return False
    assert isinstance(delivery, Mapping)
    assert isinstance(source, Mapping)
    assert isinstance(connector, Mapping)
    assert isinstance(collection, Mapping)
    assert isinstance(receipt, Mapping)
    assert isinstance(artifact, Mapping)

    string_fields = (
        (delivery, ("id", "recipient", "purpose", "created_at", "expires_at")),
        (source, ("id",)),
        (
            connector,
            ("release_id", "id", "version", "code_sha256", "contract_version"),
        ),
        (collection, ("id", "mode", "request_fingerprint")),
        (receipt, ("id", "kind", "checked_at")),
        (artifact, ("sha256", "media_type")),
    )
    for value, fields in string_fields:
        for field in fields:
            if not isinstance(value.get(field), str) or not value.get(field):
                return False
    if not isinstance(source.get("contract"), Mapping):
        return False
    if not isinstance(receipt.get("rights"), Mapping):
        return False
    if _parse_timestamp(delivery.get("created_at")) is None:
        return False
    if _parse_timestamp(delivery.get("expires_at")) is None:
        return False
    if _parse_timestamp(receipt.get("checked_at")) is None:
        return False
    if not _SHA256_RE.fullmatch(str(connector.get("code_sha256"))):
        return False
    if not _SHA256_RE.fullmatch(str(collection.get("request_fingerprint"))):
        return False
    if not _SHA256_RE.fullmatch(str(artifact.get("sha256"))):
        return False
    item_count = collection.get("item_count")
    raw_size = artifact.get("raw_size")
    if (
        isinstance(item_count, bool)
        or not isinstance(item_count, int)
        or item_count < 0
    ):
        return False
    if isinstance(raw_size, bool) or not isinstance(raw_size, int) or raw_size < 0:
        return False
    return True


def _delivery_id(envelope: Mapping[str, Any]) -> str | None:
    delivery = envelope.get("delivery")
    if not isinstance(delivery, Mapping):
        return None
    value = delivery.get("id")
    return value if isinstance(value, str) and value else None


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _reject(code: str, delivery_id: str | None) -> ConformanceResult:
    return ConformanceResult(
        accepted=False,
        code=code,
        delivery_id=delivery_id,
    )
