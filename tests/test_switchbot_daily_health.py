from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from hedp.daily_health import DailyHealthService
from hedp.storage import Storage
from hedp.adapters.switchbot.storage import SwitchBotStorage


TOKYO = ZoneInfo("Asia/Tokyo")
CHECKED = datetime(2026, 7, 21, 3, 20, tzinfo=TOKYO)


def _switchbot_health(tmp_path, *, battery=None, measurement="observed"):
    path = tmp_path / "health.db"
    storage = SwitchBotStorage(str(path))
    storage.connect()
    storage.upsert_device(
        {"deviceId": "DEVICE123456", "deviceName": "Hub",
         "deviceType": "Hub Mini"},
        datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    for hours in range(18):
        moment = (CHECKED - timedelta(hours=17 - hours)).astimezone(timezone.utc)
        storage.insert_observation({
            "device_id": "DEVICE123456", "observed_at_utc": moment.isoformat(),
            "observed_at_local": moment.astimezone(TOKYO).isoformat(),
            "timezone": "Asia/Tokyo", "observation_kind": "status_snapshot",
            "battery_percent": battery, "source": "switchbot_api_v1_1",
            "source_precision": "snapshot", "expected_interval_seconds": 3600,
            "collection_method": "open_api_v1_1",
            "measurement_status": measurement, "raw_payload_json": "{}",
        })
        storage.record_collection_event(
            "DEVICE123456", moment, success=True,
            status_body_empty=True, error_type=None, raw_payload_json="{}",
        )
    storage.commit()
    return path, storage


def test_switchbot_daily_health_accepts_empty_body_and_null_co2(tmp_path):
    path, switchbot = _switchbot_health(tmp_path)
    switchbot.close()
    warnings = []
    summary = DailyHealthService(
        Storage(str(path)), str(path), []
    )._check_switchbot(
        (CHECKED - timedelta(hours=24)).astimezone(timezone.utc),
        CHECKED.astimezone(timezone.utc), CHECKED, warnings,
    )
    assert warnings == []
    assert summary["count"] == 18


def test_switchbot_daily_health_warns_low_and_depleted_battery(tmp_path):
    path, switchbot = _switchbot_health(
        tmp_path, battery=0, measurement="battery_depleted_or_unavailable"
    )
    switchbot.close()
    warnings = []
    DailyHealthService(Storage(str(path)), str(path), [])._check_switchbot(
        (CHECKED - timedelta(hours=24)).astimezone(timezone.utc),
        CHECKED.astimezone(timezone.utc), CHECKED, warnings,
    )
    problems = {item["problem"] for item in warnings}
    assert "battery is low" in problems
    assert "measurement unavailable with depleted battery" in problems


def test_switchbot_daily_health_ignores_inactive_device(tmp_path):
    path, switchbot = _switchbot_health(tmp_path)
    switchbot._connection().execute(
        "UPDATE switchbot_devices SET enabled=0"
    )
    switchbot.commit()
    switchbot.close()
    warnings = []
    summary = DailyHealthService(
        Storage(str(path)), str(path), []
    )._check_switchbot(
        (CHECKED - timedelta(hours=24)).astimezone(timezone.utc),
        CHECKED.astimezone(timezone.utc), CHECKED, warnings,
    )
    assert warnings == []
    assert summary["metadata_counts"]["enabled_devices"] == 0
