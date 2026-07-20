#!/usr/bin/env python3
"""One-shot, read-only SwitchBot Open API v1.1 inspection."""

from __future__ import annotations

import argparse
import csv
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hedp.switchbot_client import SwitchBotClient


SENSITIVE_KEYS = {
    "authorization",
    "sign",
    "token",
    "secret",
    "nonce",
    "requestheaders",
    "request_headers",
}
PRIMARY_VALUES = ("temperature", "humidity", "CO2", "co2", "battery")


def _get_json(path: str, token: str, secret: str) -> dict[str, Any]:
    return SwitchBotClient(token, secret).get_json(path)


def _masked(value: object, length: int = 6) -> str:
    text = str(value or "")
    return text[-length:] if text else "-"


def _body(response: dict[str, Any]) -> dict[str, Any]:
    value = response.get("body")
    return value if isinstance(value, dict) else {}


def _status_success(response: dict[str, Any]) -> bool:
    return response.get("statusCode") == 100 and isinstance(
        response.get("body"), dict
    )


def _field_names(device: dict[str, Any], status: dict[str, Any] | None) -> list[str]:
    names = {str(key) for key in device}
    if status is not None:
        names.update(str(key) for key in status)
        names.update(str(key) for key in _body(status))
    return sorted(names)


def _other_numbers(status: dict[str, Any] | None) -> dict[str, int | float]:
    if status is None:
        return {}
    excluded = {value.casefold() for value in PRIMARY_VALUES}
    return {
        str(key): value
        for key, value in _body(status).items()
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and str(key).casefold() not in excluded
    }


def _cell(value: object, width: int) -> str:
    text = "" if value is None else str(value)
    if len(text) > width:
        text = f"{text[: width - 1]}…"
    return f"{text:<{width}}"


def _print_table(headers: list[str], rows: list[list[object]]) -> None:
    widths = [max(8, min(32, len(header))) for header in headers]
    for index, row in enumerate(rows):
        for column, value in enumerate(row):
            widths[column] = min(32, max(widths[column], len(str(value or ""))))
    print(" | ".join(_cell(value, widths[index]) for index, value in enumerate(headers)))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(" | ".join(_cell(value, widths[index]) for index, value in enumerate(row)))


def _safe_copy(value: object, removed: list[str], path: str = "") -> object:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            current = f"{path}.{key}" if path else str(key)
            if str(key).casefold() in SENSITIVE_KEYS:
                removed.append(current)
            else:
                result[key] = _safe_copy(item, removed, current)
        return result
    if isinstance(value, list):
        return [_safe_copy(item, removed, path) for item in value]
    return value


def _write_private(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(descriptor, content.encode())
    finally:
        os.close(descriptor)
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def inspect(token: str, secret: str, output_directory: Path) -> tuple[dict[str, Any], Path, Path]:
    devices_response = _get_json("/devices", token, secret)
    devices_body = _body(devices_response)
    physical = devices_body.get("deviceList", [])
    infrared = devices_body.get("infraredRemoteList", [])
    if not isinstance(physical, list) or not isinstance(infrared, list):
        raise ValueError("SwitchBot device lists have an unexpected shape")

    statuses = []
    for device in physical:
        device_id = device.get("deviceId") if isinstance(device, dict) else None
        if not device_id:
            statuses.append({"deviceId": None, "success": False, "error": "deviceId missing"})
            continue
        try:
            response = _get_json(f"/devices/{device_id}/status", token, secret)
            success = _status_success(response)
            statuses.append({
                "deviceId": device_id,
                "success": success,
                "response": response,
                "error": None if success else str(response.get("message", "status unsupported")),
            })
        except Exception as error:
            statuses.append({
                "deviceId": device_id,
                "success": False,
                "error": type(error).__name__,
            })

    result = {
        "inspected_at": datetime.now(timezone.utc).isoformat(),
        "api_version": "v1.1",
        "devices_response": devices_response,
        "physical_devices": physical,
        "infrared_remotes": infrared,
        "statuses": statuses,
    }
    removed: list[str] = []
    safe_result = _safe_copy(result, removed)
    safe_result["removed_sensitive_fields"] = removed
    serialized = json.dumps(safe_result, ensure_ascii=False, indent=2, sort_keys=True)
    if token in serialized or secret in serialized:
        raise RuntimeError("Credential value detected in inspection output")

    output_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    output_directory.chmod(0o700)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = output_directory / f"switchbot_devices_{timestamp}.json"
    csv_path = output_directory / f"switchbot_devices_{timestamp}.csv"
    _write_private(json_path, f"{serialized}\n")

    status_by_id = {item.get("deviceId"): item for item in statuses}
    rows = []
    for number, device in enumerate(physical, 1):
        if not isinstance(device, dict):
            continue
        status_item = status_by_id.get(device.get("deviceId"), {})
        response = status_item.get("response")
        status_body = _body(response) if isinstance(response, dict) else {}
        rows.append({
            "number": number,
            "device_id_suffix": _masked(device.get("deviceId")),
            "device_name": device.get("deviceName", ""),
            "device_type": device.get("deviceType", ""),
            "temperature": status_body.get("temperature", ""),
            "humidity": status_body.get("humidity", ""),
            "co2": status_body.get("CO2", status_body.get("co2", "")),
            "estimated_location": "",
            "official_location": "",
            "purpose": "",
            "notes": "",
        })
    fieldnames = list(rows[0]) if rows else [
        "number", "device_id_suffix", "device_name", "device_type",
        "temperature", "humidity", "co2", "estimated_location",
        "official_location", "purpose", "notes",
    ]
    from io import StringIO

    csv_buffer = StringIO()
    writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    _write_private(csv_path, csv_buffer.getvalue())
    return safe_result, json_path, csv_path


def _display(result: dict[str, Any], json_path: Path, csv_path: Path) -> None:
    physical = result["physical_devices"]
    infrared = result["infrared_remotes"]
    statuses = result["statuses"]
    status_by_id = {item.get("deviceId"): item for item in statuses}
    physical_rows = []
    for number, device in enumerate(physical, 1):
        status_item = status_by_id.get(device.get("deviceId"), {})
        response = status_item.get("response")
        status_body = _body(response) if isinstance(response, dict) else {}
        physical_rows.append([
            number,
            _masked(device.get("deviceId")),
            device.get("deviceName", ""),
            device.get("deviceType", ""),
            _masked(device.get("hubDeviceId")),
            "success" if status_item.get("success") else "failed",
            status_body.get("temperature", ""),
            status_body.get("humidity", ""),
            status_body.get("CO2", status_body.get("co2", "")),
            status_body.get("battery", ""),
            json.dumps(_other_numbers(response), ensure_ascii=False, sort_keys=True),
            ", ".join(_field_names(device, response)),
            status_item.get("error", "") or "",
        ])
    print("Physical devices")
    _print_table(
        ["No.", "ID suffix", "Name", "Type", "Hub suffix", "Status", "Temp", "Humidity", "CO2", "Battery", "Other numeric", "All fields", "Error"],
        physical_rows,
    )
    print("\nInfrared remotes")
    _print_table(
        ["No.", "ID suffix", "Name", "Remote type", "Hub suffix"],
        [[index, _masked(item.get("deviceId")), item.get("deviceName", ""), item.get("remoteType", ""), _masked(item.get("hubDeviceId"))] for index, item in enumerate(infrared, 1)],
    )
    successes = sum(bool(item.get("success")) for item in statuses)
    print(f"\nPhysical devices: {len(physical)}")
    print(f"Infrared remotes: {len(infrared)}")
    print(f"Status succeeded: {successes}")
    print(f"Status failed: {len(statuses) - successes}")
    print(f"JSON: {json_path}")
    print(f"CSV mapping table: {csv_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path("runtime/inspection"),
    )
    arguments = parser.parse_args()
    token = os.environ.get("SWITCHBOT_TOKEN", "").strip()
    secret = os.environ.get("SWITCHBOT_SECRET", "").strip()
    if not token or not secret:
        parser.error(
            "Set SWITCHBOT_TOKEN and SWITCHBOT_SECRET in the current shell; "
            "do not put them in source files or command arguments"
        )
    result, json_path, csv_path = inspect(
        token, secret, arguments.output_directory
    )
    _display(result, json_path, csv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
