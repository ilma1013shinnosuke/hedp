from __future__ import annotations

import json

import pytest
import requests

from hedp.adapters.switchbot.fast_light import (
    E26FastCommandTransport,
    FastE26Command,
    FastLightTransportError,
)


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"statusCode": 100, "message": "success", "body": {}}


def test_fast_path_sends_exactly_one_post_without_readback() -> None:
    calls: list[dict[str, object]] = []

    def post(url: str, **kwargs: object) -> FakeResponse:
        calls.append({"url": url, **kwargs})
        return FakeResponse()

    times = iter((10.0, 10.123))
    receipt = E26FastCommandTransport(
        "token",
        "secret",
        "private-device",
        request_post=post,
        monotonic=lambda: next(times),
    ).send(FastE26Command.SET_BRIGHTNESS, "72")

    assert receipt.accepted is True
    assert receipt.receipt_ms == pytest.approx(123)
    assert len(calls) == 1
    assert calls[0]["json"] == {
        "command": "setBrightness",
        "parameter": "72",
        "commandType": "command",
    }
    safe = json.dumps(receipt.safe_summary())
    assert "private-device" not in safe
    assert "token" not in safe
    assert receipt.safe_summary()["pre_read"] is False
    assert receipt.safe_summary()["post_read"] is False


@pytest.mark.parametrize(
    ("command", "parameter"),
    [
        (FastE26Command.SET_BRIGHTNESS, "0"),
        (FastE26Command.SET_BRIGHTNESS, "101"),
        (FastE26Command.SET_COLOR_TEMPERATURE, "2699"),
        (FastE26Command.SET_COLOR_TEMPERATURE, "6501"),
        (FastE26Command.SET_COLOR, "256:0:0"),
        (FastE26Command.SET_COLOR, "0:0"),
    ],
)
def test_invalid_parameters_fail_before_network(
    command: FastE26Command,
    parameter: str,
) -> None:
    called = False

    def post(*args: object, **kwargs: object) -> FakeResponse:
        nonlocal called
        called = True
        return FakeResponse()

    transport = E26FastCommandTransport(
        "token",
        "secret",
        "private-device",
        request_post=post,
    )
    with pytest.raises(ValueError):
        transport.send(command, parameter)
    assert called is False


@pytest.mark.parametrize(
    ("failure", "reason_code"),
    [
        (requests.Timeout("private URL"), "timeout"),
        (requests.ConnectionError("private URL"), "connection_failed"),
    ],
)
def test_network_failures_are_sanitized_and_never_retried(
    failure: requests.RequestException,
    reason_code: str,
) -> None:
    calls = 0

    def post(*args: object, **kwargs: object) -> FakeResponse:
        nonlocal calls
        calls += 1
        raise failure

    transport = E26FastCommandTransport(
        "private-token",
        "private-secret",
        "private-device",
        request_post=post,
    )

    with pytest.raises(FastLightTransportError) as captured:
        transport.send(FastE26Command.TURN_ON)

    assert calls == 1
    assert captured.value.reason_code == reason_code
    rendered = str(captured.value)
    assert "private" not in rendered
    assert "https://" not in rendered.casefold()


def test_http_and_json_failures_do_not_expose_the_device_url() -> None:
    class HttpFailureResponse(FakeResponse):
        def raise_for_status(self) -> None:
            raise requests.HTTPError("https://vendor/devices/private-device")

    class InvalidJsonResponse(FakeResponse):
        def json(self) -> dict[str, object]:
            raise ValueError("raw private body")

    for response, expected in (
        (HttpFailureResponse(), "http_rejected"),
        (InvalidJsonResponse(), "response_invalid"),
    ):
        transport = E26FastCommandTransport(
            "private-token",
            "private-secret",
            "private-device",
            request_post=lambda *args, response=response, **kwargs: response,
        )
        with pytest.raises(FastLightTransportError) as captured:
            transport.send(FastE26Command.TURN_ON)
        assert captured.value.reason_code == expected
        assert "private" not in str(captured.value)


def test_default_transport_reuses_one_requests_session(monkeypatch) -> None:
    created: list[object] = []
    calls: list[dict[str, object]] = []

    class FakeSession:
        def __init__(self) -> None:
            created.append(self)

        def post(self, url: str, **kwargs: object) -> FakeResponse:
            calls.append({"url": url, **kwargs})
            return FakeResponse()

    monkeypatch.setattr(
        "hedp.adapters.switchbot.fast_light.requests.Session",
        FakeSession,
    )
    transport = E26FastCommandTransport(
        "token",
        "secret",
        "private-device",
    )

    transport.send(FastE26Command.SET_BRIGHTNESS, "50")
    transport.send(FastE26Command.SET_BRIGHTNESS, "51")

    assert len(created) == 1
    assert len(calls) == 2
