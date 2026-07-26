import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from hedp.observations import Quality
from hedp.adapters.switchbot.household import SwitchBotHouseholdConfiguration
from hedp.adapters.switchbot.secondary_state import (
    DetectionContinuation,
    DetectionState,
    IlluminanceState,
    LightPower,
    PresenceState,
    RegistrationStatus,
    SecondaryDeviceKind,
    SecondaryDeviceRegistration,
    SecondaryDeviceRegistry,
    SecondaryField,
    SecondarySource,
    normalize_secondary_observation,
)
from hedp.adapters.switchbot.service import SwitchBotService
from hedp.adapters.switchbot.storage import SwitchBotStorage


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "switchbot"
    / "secondary_stage_anonymous.json"
)


def _payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _registration(item, index=1):
    status = RegistrationStatus(item["registration_status"])
    return SecondaryDeviceRegistration(
        item["target_alias"],
        SecondaryDeviceKind(item["kind"]),
        status,
        None if status is RegistrationStatus.PENDING_REGISTRATION else f"fixture-{index}",
    )


def _normalize(registration, body, *, evaluated_at=None, source=None):
    payload = _payload()
    observed_at = datetime.fromisoformat(payload["observed_at"])
    received_at = datetime.fromisoformat(payload["received_at"])
    return normalize_secondary_observation(
        registration,
        body,
        source=source or SecondarySource.OPENAPI_SNAPSHOT,
        observed_at=observed_at,
        received_at=received_at,
        evaluated_at=evaluated_at or received_at,
        stale_after=timedelta(minutes=5),
    )


def test_four_registered_kinds_normalize_without_vendor_device_type_guessing():
    items = _payload()["devices"]
    observations = [
        _normalize(_registration(item, index), item["body"])
        for index, item in enumerate(items, start=1)
    ]

    motion = observations[0]
    assert motion.field(SecondaryField.MOTION).observation.value is DetectionState.DETECTED
    assert (
        motion.field(SecondaryField.ILLUMINANCE).observation.value
        is IlluminanceState.DIM
    )
    presence = observations[1]
    assert (
        presence.field(SecondaryField.PRESENCE).observation.value
        is PresenceState.PRESENT
    )
    assert (
        presence.field(SecondaryField.DETECTION_CONTINUES).observation.value
        is DetectionContinuation.ACTIVE
    )
    strip = observations[2]
    assert strip.field(SecondaryField.POWER).observation.value is LightPower.ON
    assert strip.field(SecondaryField.BRIGHTNESS).observation.value == 35
    assert strip.field(SecondaryField.COLOR).observation.value.canonical() == "12:34:56"

    bulb = observations[3]
    assert bulb.registration_status is RegistrationStatus.PENDING_REGISTRATION
    assert bulb.quality is Quality.UNKNOWN
    assert bulb.reason == "pending_registration"
    assert bulb.fields == ()


def test_quality_cases_are_explicit_and_do_not_fabricate_values():
    payload = _payload()
    observed_at = datetime.fromisoformat(payload["observed_at"])
    cases = payload["quality_cases"]

    qualities = {}
    for index, (name, item) in enumerate(cases.items(), start=10):
        registration = SecondaryDeviceRegistration(
            f"quality-{name}",
            SecondaryDeviceKind(item["kind"]),
            RegistrationStatus.OBSERVABLE,
            f"fixture-{index}",
        )
        evaluated_at = (
            observed_at + timedelta(hours=1)
            if name == "stale"
            else observed_at + timedelta(seconds=1)
        )
        qualities[name] = _normalize(
            registration,
            item["body"],
            evaluated_at=evaluated_at,
        )

    assert qualities["missing"].quality is Quality.MISSING
    assert (
        qualities["missing"]
        .field(SecondaryField.ILLUMINANCE)
        .observation.value
        is None
    )
    assert qualities["stale"].quality is Quality.STALE
    assert all(
        item.observation.quality is Quality.STALE
        for item in qualities["stale"].fields
    )
    assert qualities["invalid"].quality is Quality.INVALID
    assert all(
        item.observation.value is None for item in qualities["invalid"].fields
        )
    assert qualities["unknown"].quality is Quality.UNKNOWN
    assert (
        qualities["unknown"]
        .field(SecondaryField.ILLUMINANCE)
        .observation.value
        is None
    )


def test_partial_ble_event_does_not_mark_unreported_fields_missing():
    registration = SecondaryDeviceRegistration(
        "presence-zone-a",
        SecondaryDeviceKind.PRESENCE_SENSOR_PRO,
        RegistrationStatus.OBSERVABLE,
        "fixture-presence",
    )
    observation = _normalize(
        registration,
        {"pirMotion": False},
        source=SecondarySource.BLE_EVENT,
    )

    assert [item.field for item in observation.fields] == [
        SecondaryField.DETECTION_CONTINUES
    ]
    assert observation.quality is Quality.GOOD


def test_alias_registry_hides_vendor_identifier_and_rejects_duplicates():
    registration = SecondaryDeviceRegistration(
        "motion-zone-a",
        SecondaryDeviceKind.MOTION_SENSOR,
        RegistrationStatus.OBSERVABLE,
        "private-fixture-id",
    )
    registry = SecondaryDeviceRegistry((registration,))

    assert registry.resolve_vendor_id("private-fixture-id") is registration
    assert "private-fixture-id" not in repr(registration)
    with pytest.raises(ValueError, match="aliases must be unique"):
        SecondaryDeviceRegistry((registration, registration))


def test_service_persists_typed_secondary_state_and_keeps_pending_neutral(tmp_path):
    strip = SecondaryDeviceRegistration(
        "strip-zone-a",
        SecondaryDeviceKind.STRIP_LIGHT_3,
        RegistrationStatus.OBSERVABLE,
        "fixture-strip",
    )
    pending_bulb = SecondaryDeviceRegistration(
        "bulb-zone-b",
        SecondaryDeviceKind.E26_SMART_BULB,
        RegistrationStatus.PENDING_REGISTRATION,
    )
    household = SwitchBotHouseholdConfiguration(
        secondary_devices=(strip, pending_bulb)
    )
    client = Mock()
    client.devices.return_value = {
        "statusCode": 100,
        "body": {
            "deviceList": [
                {
                    "deviceId": "fixture-strip",
                    "deviceName": "anonymous",
                    "deviceType": "unconfirmed-type-label",
                }
            ],
            "infraredRemoteList": [],
        },
    }
    client.status.return_value = {
        "statusCode": 100,
        "body": {"power": "on", "brightness": 42, "color": "1:2:3"},
    }
    storage = SwitchBotStorage(str(tmp_path / "secondary.db"))
    storage.connect()
    try:
        report = SwitchBotService(client, storage, household).collect()
        rows = storage.rows("SELECT * FROM switchbot_observations")
    finally:
        storage.close()

    assert client.status.call_count == 1
    assert len(rows) == 1
    row = rows[0]
    typed = json.loads(row["secondary_state_json"])
    assert row["device_alias"] == "strip-zone-a"
    assert row["secondary_device_kind"] == "strip_light_3"
    assert row["secondary_quality"] == "good"
    assert typed["target_alias"] == "strip-zone-a"
    assert {item["field"] for item in typed["fields"]} == {
        "power",
        "brightness",
        "color",
    }
    pending = next(
        item
        for item in report["results"]
        if item.get("target_alias") == "bulb-zone-b"
    )
    assert pending["registration_status"] == "pending_registration"
    assert pending["success"] is None
    assert pending["error"] is None


def test_household_file_accepts_only_typed_secondary_registration(tmp_path):
    path = tmp_path / "household.json"
    path.write_text(
        json.dumps(
            {
                "secondary_devices": [
                    {
                        "target_alias": "bulb-zone-a",
                        "kind": "e26_smart_bulb",
                        "registration_status": "pending_registration",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)

    configuration = SwitchBotHouseholdConfiguration.from_file(path)

    assert len(configuration.secondary_devices) == 1
    assert (
        configuration.secondary_devices[0].registration_status
        is RegistrationStatus.PENDING_REGISTRATION
    )
