import json
import sqlite3
from typing import Any

from hedp.adapters.switchbot.probe import ProbeDisposition
from hedp.adapters.switchbot.probe_runner import (
    run_from_environment,
    run_report_from_environment,
)

from test_switchbot_probe import FakeResponse


def test_runner_uses_read_only_baseline_and_returns_only_safe_summary(
    tmp_path,
    monkeypatch,
):
    database = tmp_path / "switchbot.sqlite"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE switchbot_devices (device_id TEXT PRIMARY KEY)"
    )
    connection.execute(
        "INSERT INTO switchbot_devices(device_id) VALUES (?)",
        ("already-known",),
    )
    connection.commit()
    connection.close()
    monkeypatch.setenv("SWITCHBOT_TOKEN", "fixture-token")
    monkeypatch.setenv("SWITCHBOT_SECRET", "fixture-secret")
    monkeypatch.setenv("SUMICORE_DATABASE_PATH", str(database))

    responses: list[dict[str, Any]] = [
        {
            "statusCode": 100,
            "body": {
                "deviceList": [
                    {
                        "deviceId": "already-known",
                        "deviceType": "Known Type",
                    },
                    {
                        "deviceId": "private-new-id",
                        "deviceName": "private-name",
                        "hubDeviceId": "private-hub",
                        "deviceType": "Exact E26 Type",
                    },
                ]
            },
        },
        {
            "statusCode": 100,
            "body": {
                "deviceId": "private-new-id",
                "power": "on",
                "brightness": 75,
            },
        },
    ]
    calls = []

    def request_get(url, **kwargs):
        calls.append(url)
        return FakeResponse(responses[len(calls) - 1])

    summary = run_from_environment(request_get=request_get)

    assert set(summary) == {
        "target_alias",
        "device_type",
        "status_fields",
        "quality",
        "observed_at",
        "persisted",
    }
    assert summary["device_type"] == "Exact E26 Type"
    assert summary["quality"] == "good"
    assert summary["persisted"] is False
    rendered = json.dumps(
        {key: value for key, value in summary.items() if key != "observed_at"}
    )
    for private in (
        "already-known",
        "private-new-id",
        "private-name",
        "private-hub",
        '"on"',
        "75",
        "fixture-token",
        "fixture-secret",
    ):
        assert private not in rendered
    assert len(calls) == 2


def test_transport_exception_is_pending_unknown_with_safe_request_counts(
    tmp_path,
    monkeypatch,
):
    database = tmp_path / "switchbot.sqlite"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE switchbot_devices (device_id TEXT PRIMARY KEY)"
    )
    connection.commit()
    connection.close()
    monkeypatch.setenv("SWITCHBOT_TOKEN", "fixture-token")
    monkeypatch.setenv("SWITCHBOT_SECRET", "fixture-secret")
    monkeypatch.setenv("SUMICORE_DATABASE_PATH", str(database))

    def unavailable(*args, **kwargs):
        raise TimeoutError("private transport detail")

    report = run_report_from_environment(request_get=unavailable)

    assert report.disposition is ProbeDisposition.PENDING_REGISTRATION
    assert report.reason == "probe_transport_unavailable"
    assert report.request_counts == (1, 0)
    assert report.public_summary["quality"] == "unknown"
    assert report.public_summary["device_type"] is None
    rendered = json.dumps(report.safe_internal_summary())
    assert "private transport detail" not in rendered
    assert "fixture-token" not in rendered
    assert "fixture-secret" not in rendered
