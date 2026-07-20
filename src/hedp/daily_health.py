from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from hedp.application import Application
from hedp.raw_data import RawData
from hedp.storage import Storage


class DailyHealthCriteria:
    EXPECTED_INTERVAL_SECONDS = 300
    GAP_WARNING_SECONDS = 900
    LATEST_WARNING_SECONDS = 900
    BACKUP_WARNING_HOURS = 48
    BATTERY_MODULES = (1, 2, 3, 4)
    FIVE_MINUTE_SOURCES = (
        "fusionsolar_device_realtime",
        "fusionsolar_battery_dc",
        "fusionsolar_alarm_current",
    )
    DAILY_SOURCES = (
        "fusionsolar",
        "fusionsolar_energy_balance",
        "fusionsolar_alarm_history",
    )


class DailyHealthService:
    def __init__(
        self,
        storage: Storage,
        database_path: str,
        device_dns: list[str],
    ) -> None:
        self.storage = storage
        self.database_path = Path(database_path).resolve()
        self.device_dns = device_dns
        self.tokyo = ZoneInfo("Asia/Tokyo")

    def check(self, checked_at: datetime, hours: int) -> dict[str, object]:
        if checked_at.tzinfo is None:
            raise ValueError("checked_at must include a timezone")
        if hours <= 0:
            raise ValueError("hours must be positive")
        checked_at = checked_at.astimezone(self.tokyo)
        window_start = checked_at - timedelta(hours=hours)
        start_utc = window_start.astimezone(ZoneInfo("UTC"))
        end_utc = checked_at.astimezone(ZoneInfo("UTC"))
        warnings: list[dict[str, object]] = []
        critical: list[dict[str, object]] = []

        integrity = self.storage.integrity_check()
        if integrity != ["ok"]:
            critical.append(
                self._issue(
                    "database", None, "SQLite integrity check failed", None,
                    "ok", integrity,
                )
            )
        all_raw = self.storage.load_rawdata()
        window_raw = [
            item for item in all_raw if start_utc <= item.timestamp <= end_utc
        ]
        by_source: dict[str, list[RawData]] = defaultdict(list)
        for item in window_raw:
            by_source[item.source].append(item)

        summaries = {
            source: self._source_summary(source, by_source.get(source, []), checked_at)
            for source in (
                *DailyHealthCriteria.FIVE_MINUTE_SOURCES,
                *DailyHealthCriteria.DAILY_SOURCES,
            )
        }
        self._check_five_minute_sources(by_source, checked_at, warnings)
        previous_date = (checked_at - timedelta(days=1)).date()
        self._check_daily_sources(all_raw, previous_date, warnings)

        application = Application(None, self.storage, None)
        battery = application.diagnose_battery_dc()
        alarms = application.diagnose_alarms()
        if battery["invalid_responses"]:
            warnings.append(
                self._issue(
                    "fusionsolar_battery_dc", None, "invalid response",
                    None, 0, battery["invalid_responses"],
                )
            )
        if battery["signal_id_changes_by_module"].get("1", 0):
            warnings.append(
                self._issue(
                    "fusionsolar_battery_dc", "module 1",
                    "Signal ID set changed", battery["latest_by_module"].get("1"),
                    0, battery["signal_id_changes_by_module"]["1"],
                )
            )
        if alarms["invalid_responses"] or alarms["non_success_responses"]:
            warnings.append(
                self._issue(
                    "alarms", None, "invalid or unsuccessful response", None,
                    0,
                    int(alarms["invalid_responses"])
                    + int(alarms["non_success_responses"]),
                )
            )
        if alarms["pagination_issues"]:
            warnings.append(
                self._issue(
                    "alarms", None, "pagination inconsistency", None, 0,
                    alarms["pagination_issues"],
                )
            )

        backup = self._backup_summary(checked_at, warnings)
        database = {
            "path": str(self.database_path),
            "size_bytes": self.database_path.stat().st_size,
            "integrity": integrity,
            "raw_data_count": self.storage.count_rawdata(),
            "record_count": self.storage.count_records(),
        }
        status = "critical" if critical else "warning" if warnings else "ok"
        return {
            "status": status,
            "checked_at": checked_at.isoformat(),
            "window_start": window_start.isoformat(),
            "window_end": checked_at.isoformat(),
            "warnings": warnings,
            "critical": critical,
            "source_summaries": summaries,
            "backup_summary": backup,
            "database_summary": database,
        }

    def _source_summary(
        self, source: str, items: list[RawData], checked_at: datetime
    ) -> dict[str, object]:
        latest = max((item.timestamp for item in items), default=None)
        metadata_counts = Counter()
        for item in items:
            metadata = item.metadata or {}
            if "device_dn" in metadata:
                metadata_counts[f"device_dn={metadata['device_dn']}"] += 1
            if "module_id" in metadata:
                metadata_counts[f"module_id={metadata['module_id']}"] += 1
        return {
            "source": source,
            "count": len(items),
            "latest_timestamp": latest.isoformat() if latest else None,
            "seconds_since_latest": (
                (checked_at - latest.astimezone(self.tokyo)).total_seconds()
                if latest
                else None
            ),
            "metadata_counts": dict(sorted(metadata_counts.items())),
        }

    def _check_five_minute_sources(
        self,
        by_source: dict[str, list[RawData]],
        checked_at: datetime,
        warnings: list[dict[str, object]],
    ) -> None:
        expected_subjects: dict[str, list[tuple[str, str]]] = {
            "fusionsolar_device_realtime": [
                ("device_dn", value) for value in self.device_dns
            ],
            "fusionsolar_battery_dc": [
                ("module_id", str(value))
                for value in DailyHealthCriteria.BATTERY_MODULES
            ],
            "fusionsolar_alarm_current": [
                ("device_dn", value) for value in self.device_dns
            ],
        }
        for source, subjects in expected_subjects.items():
            items = by_source.get(source, [])
            for metadata_key, expected_value in subjects:
                subject_items = [
                    item
                    for item in items
                    if str((item.metadata or {}).get(metadata_key))
                    == expected_value
                ]
                subject = f"{metadata_key}={expected_value}"
                if not subject_items:
                    warnings.append(
                        self._issue(
                            source, subject, "missing in checked window", None,
                            "at least one", 0,
                        )
                    )
                    continue
                timestamps = sorted({item.timestamp for item in subject_items})
                latest = timestamps[-1]
                delay = (
                    checked_at - latest.astimezone(self.tokyo)
                ).total_seconds()
                if delay >= DailyHealthCriteria.LATEST_WARNING_SECONDS:
                    warnings.append(
                        self._issue(
                            source, subject, "latest acquisition is delayed",
                            latest.isoformat(),
                            f"< {DailyHealthCriteria.LATEST_WARNING_SECONDS}s",
                            delay,
                        )
                    )
                gaps = [
                    (current - previous).total_seconds()
                    for previous, current in zip(timestamps, timestamps[1:])
                    if (current - previous).total_seconds()
                    >= DailyHealthCriteria.GAP_WARNING_SECONDS
                ]
                if gaps:
                    warnings.append(
                        self._issue(
                            source, subject, "large acquisition gap",
                            latest.isoformat(),
                            f"< {DailyHealthCriteria.GAP_WARNING_SECONDS}s",
                            max(gaps),
                        )
                    )

    def _check_daily_sources(
        self,
        all_raw: list[RawData],
        previous_date: Any,
        warnings: list[dict[str, object]],
    ) -> None:
        for source in ("fusionsolar", "fusionsolar_energy_balance"):
            matches = [
                item
                for item in all_raw
                if item.source == source and item.target_date == previous_date
            ]
            if not matches:
                warnings.append(
                    self._issue(
                        source, None, "previous-day RawData is missing", None,
                        previous_date.isoformat(), 0,
                    )
                )
            if source == "fusionsolar_energy_balance":
                for item in matches:
                    data = item.payload.get("data")
                    x_axis = data.get("xAxis") if isinstance(data, dict) else None
                    if not isinstance(x_axis, list) or len(x_axis) != 288:
                        warnings.append(
                            self._issue(
                                source, previous_date.isoformat(),
                                "xAxis length is invalid", item.timestamp.isoformat(),
                                288, len(x_axis) if isinstance(x_axis, list) else None,
                            )
                        )
                record_dates = self.storage.get_record_dates(
                    source, previous_date, previous_date
                )
                if previous_date not in record_dates:
                    warnings.append(
                        self._issue(
                            source, previous_date.isoformat(),
                            "derived Records are missing", None,
                            "Records present", 0,
                        )
                    )
        history_devices = {
            str((item.metadata or {}).get("device_dn"))
            for item in all_raw
            if item.source == "fusionsolar_alarm_history"
            and (item.metadata or {}).get("target_date")
            == previous_date.isoformat()
        }
        for device_dn in self.device_dns:
            if device_dn not in history_devices:
                warnings.append(
                    self._issue(
                        "fusionsolar_alarm_history", f"device_dn={device_dn}",
                        "previous-day history is missing", None,
                        previous_date.isoformat(), 0,
                    )
                )

    def _backup_summary(
        self,
        checked_at: datetime,
        warnings: list[dict[str, object]],
    ) -> dict[str, object]:
        backup_directory = self.database_path.parent / "backups"
        candidates = sorted(backup_directory.glob("hedp-????????-??????.db"))
        latest = max(candidates, key=lambda value: value.stat().st_mtime, default=None)
        latest_time = (
            datetime.fromtimestamp(latest.stat().st_mtime, self.tokyo)
            if latest
            else None
        )
        age_hours = (
            (checked_at - latest_time).total_seconds() / 3600
            if latest_time
            else None
        )
        if latest_time is None or age_hours >= DailyHealthCriteria.BACKUP_WARNING_HOURS:
            warnings.append(
                self._issue(
                    "backup", None, "recent backup is missing",
                    latest_time.isoformat() if latest_time else None,
                    f"< {DailyHealthCriteria.BACKUP_WARNING_HOURS}h",
                    age_hours,
                )
            )
        return {
            "directory": str(backup_directory),
            "exists": backup_directory.is_dir(),
            "latest_path": str(latest) if latest else None,
            "latest_timestamp": latest_time.isoformat() if latest_time else None,
            "age_hours": age_hours,
        }

    @staticmethod
    def _issue(
        source: str,
        subject: str | None,
        problem: str,
        latest_timestamp: str | None,
        expected: object,
        actual: object,
    ) -> dict[str, object]:
        return {
            "source": source,
            "subject": subject,
            "problem": problem,
            "latest_timestamp": latest_timestamp,
            "expected": expected,
            "actual": actual,
        }
