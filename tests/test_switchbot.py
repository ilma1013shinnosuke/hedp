import csv
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
import zipfile

from hedp.adapters.switchbot.household import SwitchBotHouseholdConfiguration
from hedp.adapters.switchbot.importer import CSV_COLUMNS, SwitchBotImporter
from hedp.adapters.switchbot.profiles import (
    expected_interval_seconds,
    normalize_status,
    profile_for,
    success_raw_retention_reasons,
)
from hedp.adapters.switchbot.service import SwitchBotService
from hedp.adapters.switchbot.storage import SwitchBotStorage


def _storage(tmp_path):
    storage = SwitchBotStorage(str(tmp_path / "test.db"))
    storage.connect()
    return storage


FILENAME_DEVICE_IDS = {
    "車内": "vehicle-sensor",
    "書斎": "study-sensor",
    "リビング": "living-sensor",
    "洗面": "washroom-sensor",
}


def test_refresh_tracks_device_name_and_location_history(tmp_path):
    storage = _storage(tmp_path)
    client = Mock()
    client.devices.return_value = {
        "statusCode": 100,
        "body": {"deviceList": [{
            "deviceId": "outdoor-sensor", "deviceName": "外",
            "deviceType": "WoIOSensor", "future": 1,
        }], "infraredRemoteList": []},
    }
    try:
        household = SwitchBotHouseholdConfiguration(
            location_history=(
                {
                    "device_id": "outdoor-sensor",
                    "location": "車内",
                    "purpose": "車内温湿度",
                    "valid_from": "2023-10-23",
                    "valid_to": "2026-07-21",
                },
                {
                    "device_id": "outdoor-sensor",
                    "location": "外",
                    "purpose": "屋外温湿度",
                    "valid_from": "2026-07-21",
                },
            )
        )
        SwitchBotService(client, storage, household).refresh_devices()
        device = storage.devices()[0]
        locations = storage.rows(
            "SELECT * FROM switchbot_device_locations ORDER BY valid_from"
        )
    finally:
        storage.close()
    assert device["current_api_name"] == "外"
    moved = [row for row in locations if row["device_id"] == "outdoor-sensor"]
    assert [(row["location"], row["valid_from"], row["valid_to"]) for row in moved] == [
        ("車内", "2023-10-23", "2026-07-21"),
        ("外", "2026-07-21", None),
    ]
    assert all(row["effective_time_precision"] == "day" for row in moved)


def test_collect_normalizes_types_empty_body_unknown_and_zero_status(tmp_path):
    storage = _storage(tmp_path)
    client = Mock()
    devices = [
        {"deviceId": "meter", "deviceName": "Meter", "deviceType": "Meter"},
        {"deviceId": "co2", "deviceName": "CO2", "deviceType": "MeterPro(CO2)"},
        {"deviceId": "plug", "deviceName": "Plug", "deviceType": "Plug Mini (JP)"},
        {"deviceId": "vac", "deviceName": "Vac", "deviceType": "K10+"},
        {"deviceId": "remote", "deviceName": "Remote", "deviceType": "Remote"},
        {"deviceId": "unknown", "deviceName": "New", "deviceType": "Future"},
        {"deviceId": "zero", "deviceName": "Dead", "deviceType": "Meter"},
    ]
    client.devices.return_value = {
        "statusCode": 100,
        "body": {"deviceList": devices, "infraredRemoteList": []},
    }
    bodies = {
        "meter": {"temperature": 20, "humidity": 50, "battery": 80},
        "co2": {"temperature": 21, "humidity": 51, "CO2": 700, "battery": 90},
        "plug": {"power": "on", "electricCurrent": 1, "voltage": 100,
                 "weight": 50, "electricityOfDay": 2},
        "vac": {"battery": 70, "onlineStatus": "online", "workingStatus": "run"},
        "remote": {}, "unknown": {"futureField": {"x": 1}},
        "zero": {"temperature": 0, "humidity": 0, "battery": 0},
    }
    client.status.side_effect = lambda device_id: {
        "statusCode": 100, "body": bodies[device_id], "message": "success"
    }
    try:
        report = SwitchBotService(client, storage).collect()
        observations = storage.rows(
            "SELECT * FROM switchbot_observations ORDER BY device_id"
        )
        events = storage.rows("SELECT * FROM switchbot_collection_events")
    finally:
        storage.close()
    assert len(report["results"]) == 7
    assert len(observations) == 7
    assert len(events) == 7
    normal_ids = {"meter", "co2", "plug", "vac"}
    assert all(
        row["raw_payload_json"] is None
        for row in observations
        if row["device_id"] in normal_ids
    )
    evidence_ids = {"remote", "unknown", "zero"}
    assert all(
        row["raw_payload_json"]
        for row in observations
        if row["device_id"] in evidence_ids
    )
    assert all(row["raw_payload_json"] is None for row in events)
    zero = next(row for row in observations if row["device_id"] == "zero")
    assert zero["temperature_c"] is None
    assert zero["relative_humidity_percent"] is None
    assert zero["battery_percent"] == 0
    assert zero["measurement_status"] == "battery_depleted_or_unavailable"
    vacuum = next(row for row in observations if row["device_id"] == "vac")
    assert vacuum["working_status"] == "run"
    assert next(item for item in report["results"] if item["device_id"] == "remote")[
        "status_body_empty"
    ] is True


def test_profiles_are_read_only_extensible_and_report_unknown_fields():
    assert profile_for("Strip Light 3").name == "light"
    assert profile_for("Color Bulb").name == "light"
    assert profile_for("Motion Sensor").name == "motion"
    assert profile_for("Future Sensor") is None

    normalized = normalize_status(
        {"deviceType": "Strip Light 3"},
        {
            "power": "on",
            "brightness": 30,
            "colorTemperature": 4000,
            "newFirmwareField": "kept-in-raw",
        },
    )

    assert normalized["status_profile"] == "light"
    assert normalized["power_state"] == "on"
    assert normalized["unknown_status_fields"] == ("newFirmwareField",)
    assert expected_interval_seconds("Strip Light 3") == 3600
    assert success_raw_retention_reasons(
        "Strip Light 3",
        {"power": "on", "newFirmwareField": "kept-in-raw"},
        normalized,
    ) == ("unknown_status_fields",)


def test_api_snapshot_marks_collection_time_as_not_device_event_time() -> None:
    collected_at = datetime(2026, 7, 25, 3, 4, 5, tzinfo=timezone.utc)

    observation = SwitchBotService._observation(
        {"deviceId": "fixture", "deviceType": "Meter"},
        {
            "statusCode": 100,
            "body": {"temperature": 20, "humidity": 50, "battery": 90},
        },
        collected_at,
    )

    assert observation["observed_at_utc"] == collected_at.isoformat()
    assert observation["source_precision"] == "collection_time_snapshot"
    assert "device_event_time" not in observation


def test_success_raw_policy_omits_normal_copy_but_keeps_schema_evidence():
    normal = normalize_status(
        {"deviceType": "Meter"},
        {"temperature": 20, "humidity": 50, "battery": 90},
    )
    assert success_raw_retention_reasons(
        "Meter",
        {"temperature": 20, "humidity": 50, "battery": 90},
        normal,
    ) == ()

    unknown = normalize_status(
        {"deviceType": "Future Sensor"},
        {"futureField": 1},
    )
    assert success_raw_retention_reasons(
        "Future Sensor",
        {"futureField": 1},
        unknown,
    ) == ("unknown_device_profile", "unknown_status_fields")

    invalid = normalize_status({"deviceType": "Meter"}, {})
    assert success_raw_retention_reasons(
        "Meter",
        [],
        invalid,
    ) == ("invalid_body_shape",)


def test_failed_switchbot_response_is_kept_only_in_collection_event(tmp_path):
    storage = _storage(tmp_path)
    client = Mock()
    client.devices.return_value = {
        "statusCode": 100,
        "body": {
            "deviceList": [
                {
                    "deviceId": "failed",
                    "deviceName": "Failed",
                    "deviceType": "Future",
                }
            ],
            "infraredRemoteList": [],
        },
    }
    client.status.return_value = {
        "statusCode": 190,
        "body": {},
        "message": "failed",
    }
    try:
        SwitchBotService(client, storage).collect()
        observations = storage.rows("SELECT * FROM switchbot_observations")
        events = storage.rows("SELECT * FROM switchbot_collection_events")
    finally:
        storage.close()

    assert observations == []
    assert len(events) == 1
    assert events[0]["success"] == 0
    assert events[0]["raw_payload_json"]


def _write_csv(path: Path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(CSV_COLUMNS)
        writer.writerows(rows)


def test_import_is_streamed_timezone_aware_idempotent_and_conflict_safe(tmp_path):
    path = tmp_path / "車内_data.csv"
    rows = [
        ["2024-01-01 00:00:00", "0", "0", "1", "-1", "0.1"],
        ["2024-01-01 00:00:00", "0", "0", "1", "-1", "0.1"],
        ["2024-01-01 00:01:01", "20", "50", "10", "9", "1"],
    ]
    _write_csv(path, rows)
    storage = _storage(tmp_path)
    importer = SwitchBotImporter(storage, FILENAME_DEVICE_IDS)
    try:
        inspection = importer.inspect(path)["files"][0]
        first = importer.run(path)["files"][0]
        second = importer.run(path)["files"][0]
        observations = storage.rows(
            "SELECT * FROM switchbot_observations ORDER BY observed_at_utc"
        )
    finally:
        storage.close()
    assert inspection["exact_or_same_value_duplicates"] == 1
    assert first["rows_inserted"] == 2
    assert second["rows_inserted"] == 0
    assert len(observations) == 2
    assert observations[0]["observed_at_utc"].startswith("2023-12-31T15:00:00")
    assert observations[0]["temperature_c"] == 0
    assert observations[0]["relative_humidity_percent"] == 0


def test_import_blocks_different_value_same_timestamp_and_bad_rows(tmp_path):
    path = tmp_path / "書斎_data分.csv"
    _write_csv(path, [
        ["2024-01-01 00:00:00", "20", "50", "10", "9", "1"],
        ["2024-01-01 00:00:00", "21", "50", "10", "9", "1"],
        ["broken", "x", "", "", "", ""],
    ])
    storage = _storage(tmp_path)
    try:
        report = SwitchBotImporter(storage, FILENAME_DEVICE_IDS).run(path)["files"][0]
    finally:
        storage.close()
    assert report["status"] == "blocked"
    assert report["timestamp_conflicts"] == 1
    assert report["invalid_rows"] == 1


def test_import_filename_mapping_accepts_decomposed_japanese(tmp_path):
    path = tmp_path / "リビング_data分.csv"
    importer = SwitchBotImporter(Mock(), FILENAME_DEVICE_IDS)
    assert importer._device_id(path) == "living-sensor"
    assert importer._device_id(tmp_path / "洗面_data.csv") == (
        "washroom-sensor"
    )


def test_canonical_key_treats_negative_and_positive_zero_as_equal():
    negative_zero = {"device_id": "device", "temperature_c": -0.0}
    positive_zero = {"device_id": "device", "temperature_c": 0.0}

    assert SwitchBotStorage.canonical_key(negative_zero) == (
        SwitchBotStorage.canonical_key(positive_zero)
    )


def test_exact_observation_conflict_keeps_both(tmp_path):
    storage = _storage(tmp_path)
    base = {
        "device_id": "device", "observed_at_utc": "2026-01-01T00:00:00+00:00",
        "observed_at_local": "2026-01-01T09:00:00+09:00",
        "timezone": "Asia/Tokyo", "observation_kind": "environment",
        "temperature_c": 20, "source": "switchbot_csv_export",
        "source_precision": "second", "expected_interval_seconds": 60,
        "collection_method": "import", "measurement_status": "observed",
    }
    try:
        assert storage.insert_observation(base) == "inserted"
        assert storage.insert_observation(base) == "duplicate"
        assert storage.insert_observation({**base, "temperature_c": 21}) == "conflict"
        storage.commit()
        assert len(storage.rows("SELECT * FROM switchbot_observations")) == 2
        assert len(storage.rows("SELECT * FROM switchbot_import_conflicts")) == 1
    finally:
        storage.close()


def test_xlsx_rows_map_excel_date_and_columns_without_dependency(tmp_path):
    path = tmp_path / "外気温_data.xlsx"
    header_cells = "".join(
        f'<c r="{chr(65 + index)}1" t="inlineStr"><is><t>{name}</t></is></c>'
        for index, name in enumerate(CSV_COLUMNS)
    )
    values = ["45292", "1.5", "40", "5", "-2", "0.2"]
    value_cells = "".join(
        f'<c r="{chr(65 + index)}2"><v>{value}</v></c>'
        for index, value in enumerate(values)
    )
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/'
        'spreadsheetml/2006/main"><sheetData>'
        f'<row r="1">{header_cells}</row><row r="2">{value_cells}</row>'
        '</sheetData></worksheet>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
    rows = list(SwitchBotImporter._rows(path))
    assert rows[0][1]["Timestamp"] == "2024-01-01 00:00:00"
    assert rows[0][1]["Temperature_Celsius(°C)"] == "1.5"
