from __future__ import annotations

from datetime import datetime, timezone

import pytest

from hedp.adapters.read_only_qualification import (
    ReadOnlyOfflineQualificationChecker,
)
from hedp.storage import RawData


NOW = datetime(2026, 7, 26, 4, 0, tzinfo=timezone.utc)
SHA = "a" * 64


@pytest.mark.parametrize(
    ("source", "payload", "metadata", "evidence_count"),
    [
        (
            "ecocute_echonet_lite",
            {
                "property_map_response_hex": "1081",
                "state_response_hex": "1081",
                "properties": [{"quality": "good"}],
            },
            {"target_alias": "water-heater"},
            2,
        ),
        (
            "qrio_read_only",
            {
                "status": {"quality": "good"},
                "health": {},
                "history": {},
                "evidence_sha256": {"status": SHA},
            },
            {
                "raw_policy": "fingerprint_only_due_to_household_secrets",
                "target_ref": "entrance-lock",
            },
            1,
        ),
        (
            "miele_read_only",
            {
                "collection_kind": "snapshot",
                "observations": [{"quality": "missing"}],
                "evidence_sha256": [SHA],
            },
            {
                "raw_policy": "fingerprint_only_due_to_household_secrets",
                "target_ref": "laundry-appliance",
            },
            1,
        ),
        (
            "smartledz_read_only",
            {
                "groups": {"quality": "good"},
                "group_details": [],
                "sensors": [],
                "schedules": [],
                "illuminance": [],
                "evidence_sha256": [SHA],
            },
            {"raw_policy": "fingerprint_only_due_to_household_secrets"},
            1,
        ),
    ],
)
def test_all_four_adapters_share_the_same_offline_gate(
    source: str,
    payload: dict[str, object],
    metadata: dict[str, object],
    evidence_count: int,
) -> None:
    report = ReadOnlyOfflineQualificationChecker().evaluate(
        RawData(source, NOW, payload, metadata=metadata)
    )

    assert report.status == "qualified"
    assert report.reasons == ()
    assert report.evidence_count == evidence_count


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"token": "hidden"}, "forbidden_key_present"),
        ({"value": "192.168.1.20"}, "network_address_present"),
        ({"value": "Bearer household-token"}, "credential_value_present"),
        ({"value": "aa:bb:cc:dd:ee:ff"}, "network_address_present"),
        ({"quality": "probably"}, "quality_value_invalid"),
        ({"value": float("nan")}, "payload_not_json_safe"),
    ],
)
def test_gate_fails_without_echoing_sensitive_values(
    payload: dict[str, object],
    reason: str,
) -> None:
    raw = RawData(
        "qrio_read_only",
        NOW,
        {
            "status": payload,
            "health": {},
            "history": {},
            "evidence_sha256": {"status": SHA},
        },
        metadata={"raw_policy": "fingerprint_only_due_to_household_secrets"},
    )

    report = ReadOnlyOfflineQualificationChecker().evaluate(raw)

    assert report.status == "not_qualified"
    assert reason in report.reasons
    assert "192.168" not in repr(report)


@pytest.mark.parametrize(
    ("metadata", "reason"),
    [
        (
            {
                "raw_policy": "fingerprint_only_due_to_household_secrets",
                "note": float("nan"),
            },
            "metadata_not_json_safe",
        ),
        (
            {
                "raw_policy": "fingerprint_only_due_to_household_secrets",
                "note": "Basic c2VjcmV0",
            },
            "credential_value_present",
        ),
    ],
)
def test_gate_applies_secret_and_json_checks_to_metadata(
    metadata: dict[str, object],
    reason: str,
) -> None:
    raw = RawData(
        "qrio_read_only",
        NOW,
        {
            "status": {"quality": "good"},
            "health": {},
            "history": {},
            "evidence_sha256": {"status": SHA},
        },
        metadata=metadata,
    )

    report = ReadOnlyOfflineQualificationChecker().evaluate(raw)

    assert report.status == "not_qualified"
    assert reason in report.reasons
    assert "c2VjcmV0" not in repr(report)
