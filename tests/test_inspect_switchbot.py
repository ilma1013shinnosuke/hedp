import csv
import importlib.util
import json
from pathlib import Path
import stat


SCRIPT = Path(__file__).parents[1] / "scripts" / "inspect_switchbot.py"
SPEC = importlib.util.spec_from_file_location("inspect_switchbot", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
inspect_switchbot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inspect_switchbot)


def test_inspection_keeps_unknown_fields_and_writes_private_files(
    tmp_path, monkeypatch
):
    responses = {
        "/devices": {
            "statusCode": 100,
            "body": {
                "deviceList": [{
                    "deviceId": "DEVICE123456",
                    "deviceName": "Meter",
                    "deviceType": "Unknown New Meter",
                    "hubDeviceId": "HUB123456",
                    "futureDeviceField": 7,
                }],
                "infraredRemoteList": [{
                    "deviceId": "REMOTE123456",
                    "deviceName": "Aircon",
                    "remoteType": "Air Conditioner",
                    "hubDeviceId": "HUB123456",
                }],
            },
            "message": "success",
        },
        "/devices/DEVICE123456/status": {
            "statusCode": 100,
            "body": {
                "deviceId": "DEVICE123456",
                "temperature": 24.5,
                "humidity": 55,
                "CO2": 600,
                "battery": 80,
                "futureNumericField": 12.3,
                "futureObject": {"value": 1},
            },
            "message": "success",
        },
    }
    monkeypatch.setattr(
        inspect_switchbot,
        "_get_json",
        lambda path, token, secret: responses[path],
    )

    result, json_path, csv_path = inspect_switchbot.inspect(
        "TOKEN_VALUE", "SECRET_VALUE", tmp_path / "inspection"
    )

    assert result["statuses"][0]["success"] is True
    saved = json_path.read_text()
    assert "futureNumericField" in saved
    assert "TOKEN_VALUE" not in saved
    assert "SECRET_VALUE" not in saved
    assert stat.S_IMODE(json_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(csv_path.stat().st_mode) == 0o600
    with csv_path.open() as file:
        row = next(csv.DictReader(file))
    assert row["device_id_suffix"] == "123456"
    assert row["estimated_location"] == ""
    assert row["official_location"] == ""
    assert row["purpose"] == ""
    assert row["notes"] == ""


def test_inspection_retains_status_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        inspect_switchbot,
        "_get_json",
        lambda path, token, secret: {
            "statusCode": 100,
            "body": {
                "deviceList": [{
                    "deviceId": "DEVICE1",
                    "deviceName": "Unsupported",
                    "deviceType": "Unknown",
                }],
                "infraredRemoteList": [],
            },
        }
        if path == "/devices"
        else (_ for _ in ()).throw(RuntimeError("API detail")),
    )

    result, _, _ = inspect_switchbot.inspect(
        "token", "secret", tmp_path / "inspection"
    )

    assert result["statuses"][0]["success"] is False
    assert result["statuses"][0]["error"] == "RuntimeError"
    assert "API detail" not in json.dumps(result)
