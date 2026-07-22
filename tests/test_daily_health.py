from datetime import datetime, timedelta, timezone
import os
from zoneinfo import ZoneInfo

from hedp.daily_health import DailyHealthService
from hedp.raw_data import RawData
from hedp.record import Record
from hedp.storage import Storage


DEVICE_DNS = ["NE=1", "NE=2"]
TOKYO = ZoneInfo("Asia/Tokyo")
CHECKED_AT = datetime(2026, 7, 21, 3, 20, tzinfo=TOKYO)


def _raw(
    source,
    timestamp,
    payload=None,
    target_date=None,
    metadata=None,
):
    return RawData(
        source,
        timestamp.astimezone(timezone.utc),
        payload or {"success": True, "data": {}},
        target_date,
        metadata,
    )


def _healthy_storage(tmp_path, *, records=True):
    database = tmp_path / "hedp.db"
    storage = Storage(str(database))
    connection = storage.connect()
    recent = CHECKED_AT - timedelta(minutes=5)
    for device_dn in DEVICE_DNS:
        storage.save_rawdata(
            _raw(
                "fusionsolar_device_realtime",
                recent,
                metadata={"device_dn": device_dn},
            )
        )
        storage.save_rawdata(
            _raw(
                "fusionsolar_alarm_current",
                recent,
                {"success": True, "data": {"totalCount": 0, "hits": []}},
                metadata={
                    "device_dn": device_dn,
                    "collection_id": f"current-{device_dn}",
                    "page_no": 1,
                    "page_size": 10,
                },
            )
        )
        storage.save_rawdata(
            _raw(
                "fusionsolar_alarm_history",
                recent,
                {"success": True, "data": {"totalCount": 0, "hits": []}},
                metadata={
                    "device_dn": device_dn,
                    "collection_id": f"history-{device_dn}",
                    "page_no": 1,
                    "page_size": 10,
                    "target_date": "2026-07-20",
                },
            )
        )
    for module_id in (1, 2, 3, 4):
        data = [{"id": 10}] if module_id == 1 else []
        storage.save_rawdata(
            _raw(
                "fusionsolar_battery_dc",
                recent,
                {"success": True, "data": data},
                metadata={"device_dn": "NE=battery", "module_id": module_id},
            )
        )
    previous = CHECKED_AT.date() - timedelta(days=1)
    storage.save_rawdata(_raw("fusionsolar", recent, target_date=previous))
    storage.save_rawdata(
        _raw(
            "fusionsolar_energy_balance",
            recent,
            {"success": True, "data": {"xAxis": list(range(288))}},
            target_date=previous,
        )
    )
    if records:
        storage.save_records(
            [
                Record(
                    "fusionsolar_energy_balance",
                    datetime(2026, 7, 20, 0, tzinfo=TOKYO).astimezone(
                        timezone.utc
                    ),
                    "productPower",
                    1,
                    "unknown",
                )
            ]
        )
    backup = tmp_path / "backups" / "hedp-20260721-030000.db"
    backup.parent.mkdir()
    backup.touch()
    timestamp = CHECKED_AT.timestamp() - 20 * 60
    os.utime(backup, (timestamp, timestamp))
    return storage, connection, database


def test_daily_health_all_sources_are_healthy(tmp_path):
    storage, connection, database = _healthy_storage(tmp_path)
    try:
        report = DailyHealthService(
            storage, str(database), DEVICE_DNS
        ).check(CHECKED_AT, 24)
    finally:
        connection.close()
    assert report["status"] == "ok"
    assert report["warnings"] == []
    assert report["critical"] == []
    assert report["database_summary"]["integrity"] == ["ok"]
    assert report["backup_summary"]["age_hours"] < 1


def test_daily_health_accepts_recent_compressed_backup(tmp_path):
    storage, connection, database = _healthy_storage(tmp_path)
    backup = tmp_path / "backups" / "hedp-20260721-030000.db"
    compressed_backup = backup.with_suffix(".db.gz")
    backup.rename(compressed_backup)
    try:
        report = DailyHealthService(
            storage, str(database), DEVICE_DNS
        ).check(CHECKED_AT, 24)
    finally:
        connection.close()
    assert not any(
        item["source"] == "backup" for item in report["warnings"]
    )
    assert report["backup_summary"]["latest_path"] == str(compressed_backup)


def test_daily_health_reports_missing_sources_devices_modules_and_records(
    tmp_path,
):
    storage, connection, database = _healthy_storage(tmp_path, records=False)
    try:
        connection.execute(
            "DELETE FROM raw_data WHERE "
            "json_extract(data, '$.source') = 'fusionsolar_device_realtime' "
            "OR json_extract(data, '$.metadata.module_id') = 4"
        )
        connection.commit()
        report = DailyHealthService(
            storage, str(database), DEVICE_DNS
        ).check(CHECKED_AT, 24)
    finally:
        connection.close()
    problems = {item["problem"] for item in report["warnings"]}
    assert report["status"] == "warning"
    assert "missing in checked window" in problems
    assert "derived Records are missing" in problems


def test_daily_health_treats_empty_battery_and_alarm_data_as_normal(tmp_path):
    storage, connection, database = _healthy_storage(tmp_path)
    try:
        report = DailyHealthService(
            storage, str(database), DEVICE_DNS
        ).check(CHECKED_AT, 24)
    finally:
        connection.close()
    assert not any(
        item["source"] in {"fusionsolar_battery_dc", "alarms"}
        for item in report["warnings"]
    )


def test_daily_health_reports_gap_delay_bad_xaxis_and_missing_history(tmp_path):
    storage, connection, database = _healthy_storage(tmp_path)
    try:
        old = CHECKED_AT - timedelta(minutes=30)
        connection.execute(
            "DELETE FROM raw_data WHERE json_extract(data, '$.source') = "
            "'fusionsolar_alarm_history' AND "
            "json_extract(data, '$.metadata.device_dn') = 'NE=2'"
        )
        connection.execute(
            "UPDATE raw_data SET data = json_set(data, '$.payload.data.xAxis', "
            "json('[1]')) WHERE json_extract(data, '$.source') = "
            "'fusionsolar_energy_balance'"
        )
        connection.commit()
        storage.save_rawdata(
            _raw(
                "fusionsolar_device_realtime",
                old,
                metadata={"device_dn": "NE=1"},
            )
        )
        report = DailyHealthService(
            storage, str(database), DEVICE_DNS
        ).check(CHECKED_AT + timedelta(minutes=20), 24)
    finally:
        connection.close()
    problems = {item["problem"] for item in report["warnings"]}
    assert "latest acquisition is delayed" in problems
    assert "large acquisition gap" in problems
    assert "xAxis length is invalid" in problems
    assert "previous-day history is missing" in problems


def test_daily_health_reports_old_or_missing_backup(tmp_path):
    storage, connection, database = _healthy_storage(tmp_path)
    try:
        report = DailyHealthService(
            storage, str(database), DEVICE_DNS
        ).check(CHECKED_AT + timedelta(hours=49), 72)
    finally:
        connection.close()
    assert any(
        item["source"] == "backup" for item in report["warnings"]
    )


def test_daily_health_reports_integrity_failure_as_critical(tmp_path):
    storage, connection, database = _healthy_storage(tmp_path)
    storage.integrity_check = lambda: ["corrupt"]
    try:
        report = DailyHealthService(
            storage, str(database), DEVICE_DNS
        ).check(CHECKED_AT, 24)
    finally:
        connection.close()
    assert report["status"] == "critical"
    assert report["critical"][0]["source"] == "database"
