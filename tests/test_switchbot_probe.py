import json

import pytest

from hedp.adapters.switchbot.probe import (
    BoundedSwitchBotReadTransport,
    ObservedDeviceTypeCount,
    PendingE26Probe,
    ProbeDisposition,
)
from hedp.adapters.switchbot.secondary_state import (
    RegistrationStatus,
    SecondaryDeviceKind,
    SecondaryDeviceRegistration,
)


class FakeResponse:
    def __init__(self, payload, *, declared_size=None):
        self._content = json.dumps(payload).encode()
        self.headers = {}
        if declared_size is not None:
            self.headers["Content-Length"] = str(declared_size)

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        for start in range(0, len(self._content), chunk_size):
            yield self._content[start : start + chunk_size]


def registration(status=RegistrationStatus.REGISTERED_UNVERIFIED, vendor_id="opaque"):
    return SecondaryDeviceRegistration(
        "bulb-zone-a",
        SecondaryDeviceKind.E26_SMART_BULB,
        status,
        vendor_id,
    )


def test_pending_registration_lists_once_and_reports_anonymous_candidates():
    transport = BoundedSwitchBotReadTransport(
        "fixture-token",
        "fixture-secret",
        request_get=lambda *args, **kwargs: FakeResponse(
            {
                "statusCode": 100,
                "body": {
                    "deviceList": [
                        {
                            "deviceId": "unlinked",
                            "deviceType": "Observed Exact Type",
                        }
                    ]
                },
            }
        ),
    )
    pending = registration(RegistrationStatus.PENDING_REGISTRATION, None)

    result = PendingE26Probe(transport).run(pending)

    assert result.disposition is ProbeDisposition.PENDING_REGISTRATION
    assert result.reason == "unique_candidate_link_not_permitted"
    assert result.candidate_device_types == (
        ObservedDeviceTypeCount("Observed Exact Type", 1),
    )
    assert set(result.safe_summary()) == {
        "target_alias",
        "device_type",
        "status_fields",
        "quality",
        "observed_at",
        "persisted",
    }
    assert [
        {"device_type": item.device_type, "count": item.count}
        for item in result.candidate_device_types
    ] == [
        {"device_type": "Observed Exact Type", "count": 1}
    ]
    assert transport.request_counts == (1, 0)


def test_pending_registration_links_only_a_permitted_unique_difference():
    responses = [
        {
            "statusCode": 100,
            "body": {
                "deviceList": [
                    {
                        "deviceId": "already-known",
                        "deviceType": "Known Type",
                    },
                    {
                        "deviceId": "new-private-id",
                        "deviceType": "Observed Exact Type",
                    },
                ]
            },
        },
        {
            "statusCode": 100,
            "body": {
                "deviceId": "new-private-id",
                "power": "off",
            },
        },
    ]
    calls = []

    def request_get(url, **kwargs):
        calls.append(url)
        return FakeResponse(responses[len(calls) - 1])

    transport = BoundedSwitchBotReadTransport(
        "fixture-token",
        "fixture-secret",
        request_get=request_get,
    )
    pending = registration(RegistrationStatus.PENDING_REGISTRATION, None)
    known = (
        SecondaryDeviceRegistration(
            "known-light",
            SecondaryDeviceKind.STRIP_LIGHT_3,
            RegistrationStatus.OBSERVABLE,
            "already-known",
        ),
    )

    result = PendingE26Probe(transport).run(
        pending,
        known_registrations=known,
        permit_unique_difference_link=True,
    )

    assert result.disposition is ProbeDisposition.VISIBLE_UNVERIFIED
    assert result.reason == "unique_new_device_candidate_requires_manual_confirmation"
    assert result.device_type == "Observed Exact Type"
    assert transport.request_counts == (1, 1)
    assert "new-private-id" not in json.dumps(result.safe_summary())


def test_visible_probe_uses_one_list_and_one_status_without_exposing_values():
    calls = []
    responses = [
        {
            "statusCode": 100,
            "body": {
                "deviceList": [
                    {
                        "deviceId": "opaque",
                        "deviceName": "private-name",
                        "hubDeviceId": "private-hub",
                        "deviceType": "Observed Exact Type",
                    }
                ]
            },
        },
        {
            "statusCode": 100,
            "body": {
                "deviceId": "opaque",
                "deviceType": "Observed Exact Type",
                "power": "on",
                "brightness": 55,
            },
        },
    ]

    def request_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(responses[len(calls) - 1])

    transport = BoundedSwitchBotReadTransport(
        "fixture-token",
        "fixture-secret",
        request_get=request_get,
    )
    result = PendingE26Probe(transport).run(registration())
    safe = result.safe_summary()

    assert result.disposition is ProbeDisposition.VISIBLE_UNVERIFIED
    assert result.status_visible is True
    assert result.device_type == "Observed Exact Type"
    assert transport.request_counts == (1, 1)
    assert all(call[1]["stream"] is True for call in calls)
    assert all(call[1]["timeout"] <= 10 for call in calls)
    rendered = json.dumps(
        {key: value for key, value in safe.items() if key != "observed_at"}
    )
    assert "opaque" not in rendered
    assert "private-name" not in rendered
    assert "private-hub" not in rendered
    assert '"on"' not in rendered
    assert "55" not in rendered
    assert safe["persisted"] is False


def test_absent_registered_target_is_pending_not_missing_or_failed():
    transport = BoundedSwitchBotReadTransport(
        "fixture-token",
        "fixture-secret",
        request_get=lambda *args, **kwargs: FakeResponse(
            {"statusCode": 100, "body": {"deviceList": []}}
        ),
    )

    result = PendingE26Probe(transport).run(registration())

    assert result.disposition is ProbeDisposition.PENDING_REGISTRATION
    assert result.reason == "registered_target_not_visible_yet"
    assert transport.request_counts == (1, 0)


def test_probe_enforces_response_bytes_and_request_counts():
    oversized = BoundedSwitchBotReadTransport(
        "fixture-token",
        "fixture-secret",
        response_byte_cap=1024,
        request_get=lambda *args, **kwargs: FakeResponse(
            {"statusCode": 100, "body": {"deviceList": []}},
            declared_size=2048,
        ),
    )
    with pytest.raises(ValueError, match="byte cap"):
        oversized.list_devices()
    with pytest.raises(PermissionError, match="limited to one"):
        oversized.list_devices()

    status_transport = BoundedSwitchBotReadTransport(
        "fixture-token",
        "fixture-secret",
        maximum_status_requests=1,
        request_get=lambda *args, **kwargs: FakeResponse(
            {"statusCode": 100, "body": {}}
        ),
    )
    status_transport.status("opaque")
    with pytest.raises(PermissionError, match="limit reached"):
        status_transport.status("opaque")


def test_probe_enforces_total_wall_clock_deadline():
    ticks = iter((0.0, 0.5, 1.1))
    transport = BoundedSwitchBotReadTransport(
        "fixture-token",
        "fixture-secret",
        wall_clock_deadline_seconds=1,
        request_get=lambda *args, **kwargs: FakeResponse(
            {"statusCode": 100, "body": {"deviceList": []}}
        ),
        monotonic=lambda: next(ticks),
    )

    with pytest.raises(TimeoutError, match="wall-clock deadline"):
        transport.list_devices()
