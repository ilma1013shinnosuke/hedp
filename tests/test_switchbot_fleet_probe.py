import json

from hedp.adapters.switchbot.fleet_probe import SecondaryFleetProbe
from hedp.adapters.switchbot.probe import BoundedSwitchBotReadTransport

from test_switchbot_probe import FakeResponse


def test_fleet_probe_lists_once_reads_four_statuses_and_hides_values():
    device_types = (
        "Motion Sensor",
        "Presence Sensor Pro",
        "Color Bulb",
        "Strip Light 3",
    )
    responses = [
        {
            "statusCode": 100,
            "body": {
                "deviceList": [
                    {
                        "deviceId": f"private-{index}",
                        "deviceName": f"private-name-{index}",
                        "deviceType": device_type,
                    }
                    for index, device_type in enumerate(device_types)
                ]
            },
        },
        *(
            {
                "statusCode": 100,
                "body": {
                    "deviceId": f"private-{index}",
                    "power": "on",
                    "brightness": 50 + index,
                },
            }
            for index in range(4)
        ),
    ]
    calls = []

    def request_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(responses[len(calls) - 1])

    transport = BoundedSwitchBotReadTransport(
        "fixture-token",
        "fixture-secret",
        maximum_status_requests=4,
        request_get=request_get,
    )
    summary = SecondaryFleetProbe(transport).run().safe_summary()

    assert transport.request_counts == (1, 4)
    assert [item["target_alias"] for item in summary["devices"]] == [
        "motion-sensor",
        "presence-sensor-pro",
        "e26-smart-bulb",
        "strip-light-3",
    ]
    assert all(item["quality"] == "good" for item in summary["devices"])
    rendered = json.dumps(summary)
    for private in (
        "private-0",
        "private-1",
        "private-2",
        "private-3",
        "private-name",
        '"on"',
        '"brightness": 50',
        '"brightness": 51',
        '"brightness": 52',
        '"brightness": 53',
        "fixture-token",
        "fixture-secret",
    ):
        assert private not in rendered


def test_fleet_probe_does_not_query_ambiguous_or_absent_types():
    listing = {
        "statusCode": 100,
        "body": {
            "deviceList": [
                {"deviceId": "motion-a", "deviceType": "Motion Sensor"},
                {"deviceId": "motion-b", "deviceType": "Motion Sensor"},
                {"deviceId": "strip", "deviceType": "Strip Light 3"},
            ]
        },
    }
    strip_status = {
        "statusCode": 100,
        "body": {"deviceId": "strip", "power": "off"},
    }
    responses = [listing, strip_status]
    calls = []

    def request_get(url, **kwargs):
        calls.append(url)
        return FakeResponse(responses[len(calls) - 1])

    transport = BoundedSwitchBotReadTransport(
        "fixture-token",
        "fixture-secret",
        maximum_status_requests=4,
        request_get=request_get,
    )
    report = SecondaryFleetProbe(transport).run()
    summary = report.safe_summary()

    assert transport.request_counts == (1, 1)
    by_alias = {item["target_alias"]: item for item in summary["devices"]}
    assert by_alias["motion-sensor"]["quality"] == "unknown"
    assert by_alias["presence-sensor-pro"]["device_type"] is None
    assert by_alias["e26-smart-bulb"]["device_type"] is None
    assert by_alias["strip-light-3"]["quality"] == "good"


def test_fleet_probe_blocks_invalid_list_without_status_requests():
    transport = BoundedSwitchBotReadTransport(
        "fixture-token",
        "fixture-secret",
        maximum_status_requests=4,
        request_get=lambda *args, **kwargs: FakeResponse(
            {"statusCode": 100, "body": {"deviceList": [{"deviceType": "Color Bulb"}]}}
        ),
    )

    summary = SecondaryFleetProbe(transport).run().safe_summary()

    assert transport.request_counts == (1, 0)
    assert all(item["quality"] == "invalid" for item in summary["devices"])
