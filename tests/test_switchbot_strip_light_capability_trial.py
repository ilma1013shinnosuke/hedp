import json
from datetime import datetime, timezone

from hedp.operations.switchbot_strip_light_capability_trial import (
    BoundedStripCapabilityCommandTransport,
    StripLightCapabilityTrial,
)
from hedp.operations.switchbot_strip_light_live_trial import (
    BoundedStripStatusTransport,
)


NOW = datetime(2026, 7, 27, 3, 0, tzinfo=timezone.utc)


class Response:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload

    def iter_content(self, chunk_size=4096):
        yield json.dumps(self.payload).encode()


class Scenario:
    def __init__(
        self,
        *,
        power="ON",
        brightness=50,
        temperature=4200,
        color="255:255:255",
        ignore_command=None,
    ):
        self.power = power
        self.brightness = brightness
        self.temperature = temperature
        self.color = color
        self.ignore_command = ignore_command
        self.post_calls = []

    def get(self, url, **kwargs):
        return Response(
            {
                "statusCode": 100,
                "body": {
                    "deviceType": "Strip Light 3",
                    "power": self.power,
                    "brightness": self.brightness,
                    "colorTemperature": self.temperature,
                    "color": self.color,
                },
            }
        )

    def post(self, url, **kwargs):
        body = kwargs["json"]
        self.post_calls.append(body)
        command = body["command"]
        if command == self.ignore_command:
            return Response({"statusCode": 100})
        parameter = body["parameter"]
        if command == "turnOn":
            self.power = "ON"
        elif command == "turnOff":
            self.power = "OFF"
        elif command == "setBrightness":
            self.brightness = int(parameter)
        elif command == "setColorTemperature":
            self.temperature = int(parameter)
        elif command == "setColor":
            self.color = parameter
        return Response({"statusCode": 100})


def run_trial(scenario):
    status = BoundedStripStatusTransport(
        "fixture-token",
        "fixture-secret",
        maximum_status_requests=30,
        request_get=scenario.get,
        monotonic=lambda: 1.0,
    )
    commands = BoundedStripCapabilityCommandTransport(
        "fixture-token",
        "fixture-secret",
        "private-strip-id",
        request_post=scenario.post,
        monotonic=lambda: 1.0,
    )
    return StripLightCapabilityTrial(
        status,
        commands,
        vendor_device_id="private-strip-id",
        clock=lambda: NOW,
        sleeper=lambda _: None,
        readback_delays=(0,),
    ).run()


def test_all_capabilities_are_verified_and_original_state_is_restored():
    scenario = Scenario()
    result = run_trial(scenario)

    assert result.reason == "all_capabilities_changed_and_restored"
    assert result.temperature_changed is True
    assert result.temperature_restored is True
    assert result.color_changed is True
    assert result.color_restored is True
    assert result.power_off_confirmed is True
    assert result.power_on_confirmed is True
    assert result.final_state_matches is True
    assert result.final_power_matches is True
    assert result.final_brightness_matches is True
    assert result.final_temperature_matches is True
    assert result.final_color_matches is True
    assert [item["command"] for item in scenario.post_calls] == [
        "setColorTemperature",
        "setColorTemperature",
        "setColor",
        "setColor",
        "setColorTemperature",
        "turnOff",
        "turnOn",
    ]


def test_colored_initial_state_is_not_changed_without_observable_mode():
    scenario = Scenario(color="255:0:0")
    result = run_trial(scenario)

    assert result.reason == "initial_color_mode_ambiguous"
    assert result.eligible is False
    assert scenario.post_calls == []


def test_failure_stops_later_stages_and_runs_bounded_compensation():
    scenario = Scenario(ignore_command="setColor")
    result = run_trial(scenario)

    assert result.reason.startswith("color_change_unconfirmed_")
    assert result.power_off_confirmed is False
    assert result.compensation_attempted is True
    assert result.command_requests <= 11


def test_safe_summary_does_not_contain_values_or_private_data():
    scenario = Scenario()
    result = run_trial(scenario)
    rendered = json.dumps(result.safe_summary())

    assert "private-strip-id" not in rendered
    assert "fixture-token" not in rendered
    assert "4200" not in rendered
    assert "255:255:255" not in rendered
