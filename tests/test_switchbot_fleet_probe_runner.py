import json

import pytest
import requests

from hedp.adapters.switchbot.fleet_probe_runner import run_from_environment

from test_switchbot_probe import FakeResponse


def test_fleet_runner_uses_secrets_only_for_transport_and_returns_safe_output(
    monkeypatch,
):
    monkeypatch.setenv("SWITCHBOT_TOKEN", "fixture-token")
    monkeypatch.setenv("SWITCHBOT_SECRET", "fixture-secret")
    listing = {
        "statusCode": 100,
        "body": {
            "deviceList": [
                {"deviceId": "private-bulb", "deviceType": "Color Bulb"}
            ]
        },
    }
    status = {
        "statusCode": 100,
        "body": {
            "deviceId": "private-bulb",
            "power": "on",
            "brightness": 77,
        },
    }
    responses = [listing, status]
    calls = []

    def request_get(url, **kwargs):
        calls.append(url)
        return FakeResponse(responses[len(calls) - 1])

    summary = run_from_environment(request_get=request_get)

    assert summary["list_requests"] == 1
    assert summary["status_requests"] == 1
    assert summary["persisted"] is False
    assert summary["probe_status"] == "completed"
    assert summary["reason"] == "probe_completed"
    bulb = next(
        item
        for item in summary["devices"]
        if item["target_alias"] == "e26-smart-bulb"
    )
    assert bulb["device_type"] == "Color Bulb"
    assert bulb["quality"] == "good"
    assert bulb["status_fields"] == ["brightness", "deviceId", "power"]
    assert set(bulb) == {
        "target_alias",
        "device_type",
        "status_fields",
        "quality",
        "observed_at",
        "persisted",
    }
    rendered = json.dumps(summary)
    for private in (
        "private-bulb",
        '"on"',
        "fixture-token",
        "fixture-secret",
    ):
        assert private not in rendered


def test_fleet_runner_transport_failure_is_safe_unknown(monkeypatch):
    monkeypatch.setenv("SWITCHBOT_TOKEN", "fixture-token")
    monkeypatch.setenv("SWITCHBOT_SECRET", "fixture-secret")

    def unavailable(*args, **kwargs):
        raise TimeoutError("private transport failure")

    summary = run_from_environment(request_get=unavailable)

    assert summary["list_requests"] == 1
    assert summary["status_requests"] == 0
    assert summary["probe_status"] == "unavailable"
    assert summary["reason"] == "probe_timeout"
    assert all(item["quality"] == "unknown" for item in summary["devices"])
    rendered = json.dumps(summary)
    assert "private transport failure" not in rendered
    assert "fixture-token" not in rendered
    assert "fixture-secret" not in rendered


@pytest.mark.parametrize(
    ("status_code", "expected_reason"),
    [
        (400, "probe_http_error"),
        (401, "probe_authentication_rejected"),
        (403, "probe_access_forbidden"),
        (429, "probe_rate_limited"),
        (503, "probe_vendor_unavailable"),
    ],
)
def test_fleet_runner_classifies_http_failure_without_response_body(
    monkeypatch,
    status_code,
    expected_reason,
):
    monkeypatch.setenv("SWITCHBOT_TOKEN", "fixture-token")
    monkeypatch.setenv("SWITCHBOT_SECRET", "fixture-secret")

    def rejected(*args, **kwargs):
        response = requests.Response()
        response.status_code = status_code
        response._content = b'{"private":"do-not-return"}'
        raise requests.HTTPError("private response", response=response)

    summary = run_from_environment(request_get=rejected)

    assert summary["reason"] == expected_reason
    rendered = json.dumps(summary)
    assert "do-not-return" not in rendered
    assert "private response" not in rendered
