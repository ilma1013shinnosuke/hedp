"""Offline qualification gate shared by read-only device adapters."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from typing import Mapping

from hedp.observations import Quality
from hedp.storage import RawData


SUPPORTED_SOURCES = frozenset(
    {
        "ecocute_echonet_lite",
        "fusionsolar_modbus_tcp",
        "qrio_read_only",
        "miele_read_only",
        "smartledz_read_only",
    }
)
_FINGERPRINT_ONLY_SOURCES = frozenset(
    {"qrio_read_only", "miele_read_only", "smartledz_read_only"}
)
_REQUIRED_PAYLOAD_KEYS = {
    "ecocute_echonet_lite": frozenset(
        {"property_map_response_hex", "state_response_hex", "properties"}
    ),
    "fusionsolar_modbus_tcp": frozenset({"ranges"}),
    "qrio_read_only": frozenset({"status", "health", "history", "evidence_sha256"}),
    "miele_read_only": frozenset(
        {"collection_kind", "observations", "evidence_sha256"}
    ),
    "smartledz_read_only": frozenset(
        {
            "groups",
            "group_details",
            "sensors",
            "schedules",
            "illuminance",
            "evidence_sha256",
        }
    ),
}
_FORBIDDEN_KEY_PARTS = frozenset(
    {
        "authorization",
        "cookie",
        "credential",
        "device_id",
        "gateway_id",
        "host",
        "ip_address",
        "lock_id",
        "mac_address",
        "password",
        "secret",
        "serial",
        "source_device_id",
        "source_lock_id",
        "ssid",
        "token",
        "udn",
    }
)
_IPV4 = re.compile(
    r"(?<!\d)(?:"
    r"(?:25[0-5]|2[0-4]\d|1?\d?\d)\."
    r"){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?!\d)"
)
_MAC_ADDRESS = re.compile(
    r"(?i)(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])"
)
_CREDENTIAL_VALUE = re.compile(
    r"(?i)(?:\b(?:bearer|basic)\s+[a-z0-9._~+/=-]+|"
    r"\b(?:access_token|refresh_token|client_secret|password)\s*[:=])"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HEX = re.compile(r"^(?:[0-9a-f]{2})+$")
_QUALITY_VALUES = frozenset(item.value for item in Quality)


@dataclass(frozen=True)
class OfflineQualificationReport:
    status: str
    source: str
    reasons: tuple[str, ...]
    payload_bytes: int
    evidence_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "source": self.source,
            "reasons": list(self.reasons),
            "payload_bytes": self.payload_bytes,
            "evidence_count": self.evidence_count,
        }


class ReadOnlyOfflineQualificationChecker:
    """Fail closed without echoing payload values or household identifiers."""

    maximum_payload_bytes = 256 * 1024

    def evaluate(self, raw_data: RawData) -> OfflineQualificationReport:
        reasons: list[str] = []
        if raw_data.source not in SUPPORTED_SOURCES:
            reasons.append("source_not_supported")
        if raw_data.timestamp.tzinfo is None or raw_data.timestamp.utcoffset() is None:
            reasons.append("timestamp_not_timezone_aware")
        try:
            encoded = json.dumps(
                raw_data.payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError):
            encoded = b""
            reasons.append("payload_not_json_safe")
        try:
            json.dumps(
                raw_data.metadata,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError):
            reasons.append("metadata_not_json_safe")
        if len(encoded) > self.maximum_payload_bytes:
            reasons.append("payload_too_large")
        if raw_data.source in _REQUIRED_PAYLOAD_KEYS:
            missing = _REQUIRED_PAYLOAD_KEYS[raw_data.source].difference(
                raw_data.payload
            )
            if missing:
                reasons.append("required_payload_key_missing")
        if _contains_forbidden_key(raw_data.payload) or _contains_forbidden_key(
            raw_data.metadata
        ):
            reasons.append("forbidden_key_present")
        if _contains_network_address(raw_data.payload) or _contains_network_address(
            raw_data.metadata
        ):
            reasons.append("network_address_present")
        if _contains_credential_value(raw_data.payload) or _contains_credential_value(
            raw_data.metadata
        ):
            reasons.append("credential_value_present")
        if _contains_nonfinite(raw_data.payload) or _contains_nonfinite(
            raw_data.metadata
        ):
            reasons.append("nonfinite_number_present")
        if _has_invalid_quality(raw_data.payload):
            reasons.append("quality_value_invalid")
        evidence_count, evidence_valid = _validate_evidence(raw_data)
        if not evidence_valid:
            reasons.append("evidence_invalid")
        if raw_data.source in _FINGERPRINT_ONLY_SOURCES:
            policy = (
                raw_data.metadata.get("raw_policy")
                if isinstance(raw_data.metadata, Mapping)
                else None
            )
            if policy != "fingerprint_only_due_to_household_secrets":
                reasons.append("fingerprint_only_policy_missing")
        return OfflineQualificationReport(
            status="qualified" if not reasons else "not_qualified",
            source=raw_data.source,
            reasons=tuple(dict.fromkeys(reasons)),
            payload_bytes=len(encoded),
            evidence_count=evidence_count,
        )


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                return True
            normalized = key.casefold().replace("-", "_")
            if normalized in _FORBIDDEN_KEY_PARTS:
                return True
            if _contains_forbidden_key(nested):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _contains_network_address(value: object) -> bool:
    if isinstance(value, str):
        return _IPV4.search(value) is not None or _MAC_ADDRESS.search(value) is not None
    if isinstance(value, Mapping):
        return any(_contains_network_address(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_network_address(item) for item in value)
    return False


def _contains_credential_value(value: object) -> bool:
    if isinstance(value, str):
        return _CREDENTIAL_VALUE.search(value) is not None
    if isinstance(value, Mapping):
        return any(_contains_credential_value(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_credential_value(item) for item in value)
    return False


def _contains_nonfinite(value: object) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, Mapping):
        return any(_contains_nonfinite(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_nonfinite(item) for item in value)
    return False


def _has_invalid_quality(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key == "quality" and (
                not isinstance(nested, str) or nested not in _QUALITY_VALUES
            ):
                return True
            if _has_invalid_quality(nested):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_has_invalid_quality(item) for item in value)
    return False


def _validate_evidence(raw_data: RawData) -> tuple[int, bool]:
    evidence = raw_data.payload.get("evidence_sha256")
    if raw_data.source == "ecocute_echonet_lite":
        property_map = raw_data.payload.get("property_map_response_hex")
        state_responses = raw_data.payload.get("state_response_hex")
        if isinstance(state_responses, str):
            # Backward-compatible acceptance of the original single batch.
            values = (property_map, state_responses)
        elif isinstance(state_responses, list) and state_responses:
            values = (property_map, *state_responses)
        else:
            return 0, False
        return len(values), all(
            isinstance(value, str) and _HEX.fullmatch(value) is not None
            for value in values
        )
    if raw_data.source == "fusionsolar_modbus_tcp":
        ranges = raw_data.payload.get("ranges")
        if not isinstance(ranges, list) or not ranges:
            return 0, False
        return len(ranges), all(_valid_modbus_range(item) for item in ranges)
    if isinstance(evidence, str):
        values = (evidence,)
    elif isinstance(evidence, Mapping):
        values = tuple(evidence.values())
    elif isinstance(evidence, list):
        values = tuple(evidence)
    else:
        return 0, False
    return len(values), bool(values) and all(
        isinstance(value, str) and _SHA256.fullmatch(value) is not None
        for value in values
    )


def _valid_modbus_range(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    if set(value) != {"name", "function_code", "start_address", "registers"}:
        return False
    name = value.get("name")
    function_code = value.get("function_code")
    start_address = value.get("start_address")
    registers = value.get("registers")
    if not isinstance(name, str) or not name or len(name) > 64:
        return False
    if function_code not in {3, 4}:
        return False
    if (
        not isinstance(start_address, int)
        or isinstance(start_address, bool)
        or not 0 <= start_address <= 65535
    ):
        return False
    if not isinstance(registers, list) or not 1 <= len(registers) <= 125:
        return False
    if start_address + len(registers) > 65536:
        return False
    return all(
        isinstance(register, int)
        and not isinstance(register, bool)
        and 0 <= register <= 65535
        for register in registers
    )
