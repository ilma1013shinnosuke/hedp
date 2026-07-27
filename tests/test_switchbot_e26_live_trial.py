import json
from datetime import datetime, timezone

from hedp.adapters.switchbot.e26_live_trial import (
    BoundedE26TrialTransport,
    E26BrightnessTrial,
)


NOW = datetime(2026, 7, 27, 0, 0, tzinfo=timezone.utc)


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("fixture HTTP failure")

    def iter_content(self, chunk_size=4096):
        yield json.dumps(self.payload).encode()


class Scenario:
    def __init__(self, *, power="ON", brightness=50, apply_change=True):
        self.power = power
        self.brightness = brightness
        self.apply_change = apply_change
        self.get_calls = []
        self.post_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        if url.endswith("/devices"):
            return Response(
                {
                    "statusCode": 100,
                    "body": {
                        "deviceList": [
                            {
                                "deviceId": "private-device-id",
                                "deviceType": "Color Bulb",
                            }
                        ]
                    },
                }
            )
        return Response(
            {
                "statusCode": 100,
                "body": {
                    "deviceType": "Color Bulb",
                    "power": self.power,
                    "brightness": self.brightness,
                },
            }
        )

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        if self.apply_change:
            self.brightness = int(kwargs["json"]["parameter"])
        return Response({"statusCode": 100, "body": {}})


def trial(scenario):
    transport = BoundedE26TrialTransport(
        "fixture-token",
        "fixture-secret",
        request_get=scenario.get,
        request_post=scenario.post,
        monotonic=lambda: 1.0,
    )
    return E26BrightnessTrial(
        transport,
        clock=lambda: NOW,
        sleeper=lambda _: None,
        readback_delays=(0,),
    ).run()


def test_e26_trial_changes_five_points_and_restores_without_exposing_values():
    scenario = Scenario(brightness=50)
    result = trial(scenario)
    summary = result.safe_summary()

    assert result.reason == "changed_and_restored"
    assert result.change_confirmed is True
    assert result.restore_confirmed is True
    assert result.final_state_matches is True
    assert len(scenario.post_calls) == 2
    assert scenario.post_calls[0][1]["json"] == {
        "command": "setBrightness",
        "parameter": "55",
        "commandType": "command",
    }
    assert scenario.post_calls[1][1]["json"]["parameter"] == "50"
    rendered = json.dumps(summary)
    assert "private-device-id" not in rendered
    assert "fixture-token" not in rendered
    assert "55" not in rendered
    assert summary["stopped_after_e26"] is True


def test_power_off_skips_without_command():
    scenario = Scenario(power="OFF", brightness=50)
    result = trial(scenario)

    assert result.reason == "initial_power_off"
    assert result.change_attempted is False
    assert scenario.post_calls == []


def test_boundary_brightness_skips_without_command():
    scenario = Scenario(brightness=100)
    result = trial(scenario)

    assert result.reason == "initial_brightness_boundary"
    assert result.change_attempted is False
    assert scenario.post_calls == []


def test_unconfirmed_change_still_restores_original_value():
    scenario = Scenario(brightness=60, apply_change=False)
    result = trial(scenario)

    assert result.reason == "change_unconfirmed_restored"
    assert result.change_confirmed is False
    assert result.restore_attempted is True
    assert result.restore_confirmed is True
    assert len(scenario.post_calls) == 2


def test_ambiguous_e26_stops_before_status_or_command():
    scenario = Scenario()

    def ambiguous(url, **kwargs):
        return Response(
            {
                "statusCode": 100,
                "body": {
                    "deviceList": [
                        {"deviceId": "one", "deviceType": "Color Bulb"},
                        {"deviceId": "two", "deviceType": "Color Bulb"},
                    ]
                },
            }
        )

    scenario.get = ambiguous
    result = trial(scenario)

    assert result.reason == "exact_e26_not_unique"
    assert result.status_requests == 0
    assert result.command_requests == 0
