from __future__ import annotations

import json

import pytest

from hedp.adapters.switchbot.fast_light import (
    FastLightCommand,
    StripLight3FastCommandTransport,
)
from hedp.adapters.switchbot.strip_light_fast_runner import run


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"statusCode": 100, "message": "success", "body": {}}


@pytest.mark.parametrize(
    ("command", "parameter", "expected"),
    [
        (FastLightCommand.TURN_ON, "default", "default"),
        (FastLightCommand.TURN_OFF, "default", "default"),
        (FastLightCommand.SET_BRIGHTNESS, "0", "0"),
        (FastLightCommand.SET_BRIGHTNESS, "100", "100"),
        (FastLightCommand.SET_COLOR_TEMPERATURE, "2700", "2700"),
        (FastLightCommand.SET_COLOR_TEMPERATURE, "6500", "6500"),
        (FastLightCommand.SET_COLOR, "255:0:8", "255:0:8"),
    ],
)
def test_strip_light_fast_path_validates_and_sends_one_post(
    command: FastLightCommand,
    parameter: str,
    expected: str,
) -> None:
    calls: list[dict[str, object]] = []

    def post(url: str, **kwargs: object) -> FakeResponse:
        calls.append({"url": url, **kwargs})
        return FakeResponse()

    receipt = StripLight3FastCommandTransport(
        "token",
        "secret",
        "private-strip",
        request_post=post,
    ).send(command, parameter)

    assert receipt.accepted is True
    assert len(calls) == 1
    assert calls[0]["json"] == {
        "command": command.value,
        "parameter": expected,
        "commandType": "command",
    }
    safe = json.dumps(receipt.safe_summary())
    assert "private-strip" not in safe
    assert "token" not in safe
    assert receipt.safe_summary()["target_alias"] == "strip-light-3"


@pytest.mark.parametrize(
    ("command", "parameter"),
    [
        (FastLightCommand.SET_BRIGHTNESS, "-1"),
        (FastLightCommand.SET_BRIGHTNESS, "101"),
        (FastLightCommand.SET_COLOR_TEMPERATURE, "2699"),
        (FastLightCommand.SET_COLOR_TEMPERATURE, "6501"),
        (FastLightCommand.SET_COLOR, "1:2"),
        (FastLightCommand.SET_COLOR, "1:2:256"),
    ],
)
def test_strip_light_invalid_values_fail_before_network(
    command: FastLightCommand,
    parameter: str,
) -> None:
    called = False

    def post(*args: object, **kwargs: object) -> FakeResponse:
        nonlocal called
        called = True
        return FakeResponse()

    transport = StripLight3FastCommandTransport(
        "token",
        "secret",
        "private-strip",
        request_post=post,
    )
    with pytest.raises(ValueError):
        transport.send(command, parameter)
    assert called is False


def test_strip_light_runner_requires_private_binding() -> None:
    with pytest.raises(RuntimeError, match="environment is incomplete"):
        run(
            ["brightness", "50"],
            environment={
                "SWITCHBOT_TOKEN": "token",
                "SWITCHBOT_SECRET": "secret",
            },
        )
