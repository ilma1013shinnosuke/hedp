import json
from datetime import datetime, timezone

from hedp.operations.switchbot_strip_light_live_trial import (
    BoundedStripCommandTransport,
    BoundedStripStatusTransport,
    StripLightBrightnessTrial,
)


NOW = datetime(2026, 7, 27, 2, 0, tzinfo=timezone.utc)


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("fixture HTTP failure")

    def json(self):
        return self.payload

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
        return Response(
            {
                "statusCode": 100,
                "body": {
                    "deviceType": "Strip Light 3",
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
    status_transport = BoundedStripStatusTransport(
        "fixture-token",
        "fixture-secret",
        request_get=scenario.get,
        monotonic=lambda: 1.0,
    )
    command_transport = BoundedStripCommandTransport(
        "fixture-token",
        "fixture-secret",
        "private-strip-id",
        request_post=scenario.post,
        monotonic=lambda: 1.0,
    )
    return StripLightBrightnessTrial(
        status_transport,
        command_transport,
        vendor_device_id="private-strip-id",
        clock=lambda: NOW,
        sleeper=lambda _: None,
        readback_delays=(0,),
    ).run()


def test_strip_trial_changes_five_points_and_restores_through_gate():
    scenario = Scenario(brightness=50)
    result = trial(scenario)

    assert result.reason == "changed_and_restored"
    assert result.reader_qualified is True
    assert result.writer_qualified is True
    assert result.gate_qualified is True
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
    rendered = json.dumps(result.safe_summary())
    assert "private-strip-id" not in rendered
    assert "fixture-token" not in rendered
    assert "55" not in rendered


def test_strip_power_off_skips_without_command():
    scenario = Scenario(power="OFF", brightness=50)
    result = trial(scenario)

    assert result.reason == "initial_power_off"
    assert result.change_attempted is False
    assert scenario.post_calls == []


def test_strip_boundary_skips_without_command():
    scenario = Scenario(brightness=100)
    result = trial(scenario)

    assert result.reason == "initial_brightness_boundary"
    assert result.change_attempted is False
    assert scenario.post_calls == []


def test_strip_unconfirmed_change_still_restores():
    scenario = Scenario(brightness=60, apply_change=False)
    result = trial(scenario)

    assert result.reason == "change_unconfirmed_restored"
    assert result.change_confirmed is False
    assert result.restore_attempted is True
    assert result.restore_confirmed is True
    assert len(scenario.post_calls) == 2


def test_wrong_device_type_stops_before_command():
    scenario = Scenario()

    def wrong_type(url, **kwargs):
        return Response(
            {
                "statusCode": 100,
                "body": {
                    "deviceType": "Color Bulb",
                    "power": "ON",
                    "brightness": 50,
                },
            }
        )

    scenario.get = wrong_type
    result = trial(scenario)

    assert result.reason == "initial_state_invalid"
    assert result.command_requests == 0
