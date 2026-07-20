from collections import Counter
from datetime import date, timedelta
from datetime import datetime
import math
from typing import Optional
from zoneinfo import ZoneInfo

from hedp.fusionsolar_collector import FusionSolarCollector
from hedp.fusionsolar_alarm_collector import FusionSolarAlarmCollector
from hedp.fusionsolar_battery_dc_collector import (
    FusionSolarBatteryDcCollector,
)
from hedp.fusionsolar_energy_balance_collector import (
    FusionSolarEnergyBalanceCollector,
)
from hedp.fusionsolar_device_realtime_collector import (
    FusionSolarDeviceRealtimeCollector,
)
from hedp.fusionsolar_energy_balance_record_builder import (
    FusionSolarEnergyBalanceRecordBuilder,
)
from hedp.fusionsolar_record_builder import FusionSolarRecordBuilder
from hedp.raw_data import RawData
from hedp.storage import Storage


class Application:
    QUALITY_UNITS = {
        "productPower": "kW",
        "inverterPower": "kW",
        "onGridPower": "kW",
        "buyPower": "kW",
        "powerProfit": "JPY",
    }
    REQUIRED_QUALITY_METRICS = {
        "productPower",
        "inverterPower",
        "onGridPower",
        "powerProfit",
    }
    EXPECTED_INTERVAL_MINUTES = 60

    def __init__(
        self,
        collector: Optional[FusionSolarCollector],
        storage: Storage,
        record_builder: Optional[FusionSolarRecordBuilder],
        energy_balance_collector: Optional[
            FusionSolarEnergyBalanceCollector
        ] = None,
        device_realtime_collector: Optional[
            FusionSolarDeviceRealtimeCollector
        ] = None,
        energy_balance_record_builder: Optional[
            FusionSolarEnergyBalanceRecordBuilder
        ] = None,
        battery_dc_collector: Optional[
            FusionSolarBatteryDcCollector
        ] = None,
        alarm_collector: Optional[FusionSolarAlarmCollector] = None,
    ) -> None:
        self.collector = collector
        self.storage = storage
        self.record_builder = record_builder
        self.energy_balance_collector = energy_balance_collector
        self.device_realtime_collector = device_realtime_collector
        self.energy_balance_record_builder = energy_balance_record_builder
        self.battery_dc_collector = battery_dc_collector
        self.alarm_collector = alarm_collector

    def run(self) -> RawData:
        if self.collector is None or self.record_builder is None:
            raise RuntimeError("Station collector is not configured")
        raw_data = self.collector.collect()
        self.storage.save_rawdata(raw_data)
        records = self.record_builder.build(raw_data)
        self.storage.save_records(records)
        return raw_data

    def run_range(
        self, start_date: date, end_date: date
    ) -> list[RawData]:
        if self.collector is None or self.record_builder is None:
            raise RuntimeError("Station collector is not configured")
        raw_data_list = self.collector.collect_range(start_date, end_date)
        for raw_data in raw_data_list:
            self.storage.save_rawdata(raw_data)
            records = self.record_builder.build(raw_data)
            self.storage.save_records(records)
        return raw_data_list

    def run_energy_balance_for_date(self, target_date: date) -> RawData:
        if self.energy_balance_collector is None:
            raise RuntimeError("Energy-balance collector is not configured")
        raw_data = self.energy_balance_collector.collect_for_date(target_date)
        self.storage.save_rawdata(raw_data)
        if self.energy_balance_record_builder is not None:
            self.storage.save_records(
                self.energy_balance_record_builder.build(raw_data)
            )
        return raw_data

    def run_energy_balance_range(
        self, start_date: date, end_date: date
    ) -> list[RawData]:
        if self.energy_balance_collector is None:
            raise RuntimeError("Energy-balance collector is not configured")
        raw_data_list = self.energy_balance_collector.collect_range(
            start_date, end_date
        )
        for raw_data in raw_data_list:
            self.storage.save_rawdata(raw_data)
            if self.energy_balance_record_builder is not None:
                self.storage.save_records(
                    self.energy_balance_record_builder.build(raw_data)
                )
        return raw_data_list

    def build_energy_balance_records(
        self, start_date: date, end_date: date
    ) -> int:
        if self.energy_balance_record_builder is None:
            raise RuntimeError("Energy-balance record builder is not configured")
        count = 0
        for raw_data in self.storage.load_rawdata_for_range(
            "fusionsolar_energy_balance", start_date, end_date
        ):
            records = self.energy_balance_record_builder.build(raw_data)
            self.storage.save_records(records)
            count += len(records)
        return count

    def run_device_realtime(
        self, device_dns: list[str]
    ) -> tuple[list[RawData], list[tuple[str, str]]]:
        if self.device_realtime_collector is None:
            raise RuntimeError("Device-realtime collector is not configured")
        collected, failures = self.device_realtime_collector.collect_devices(
            device_dns
        )
        for raw_data in collected:
            self.storage.save_rawdata(raw_data)
        return collected, failures

    def run_battery_dc(
        self, device_dn: str, sigids: str, module_ids: list[int]
    ) -> tuple[list[RawData], list[tuple[int, str]]]:
        if self.battery_dc_collector is None:
            raise RuntimeError("Battery DC collector is not configured")
        collected, failures = self.battery_dc_collector.collect_modules(
            device_dn, sigids, module_ids
        )
        for raw_data in collected:
            self.storage.save_rawdata(raw_data)
        return collected, failures

    def run_current_alarms(
        self, device_dns: list[str]
    ) -> tuple[list[RawData], list[tuple[str, str]]]:
        if self.alarm_collector is None:
            raise RuntimeError("Alarm collector is not configured")
        collected, failures = self.alarm_collector.collect_current_devices(
            device_dns
        )
        for raw_data in collected:
            self.storage.save_rawdata(raw_data)
        return collected, failures

    def run_alarm_history(
        self, device_dns: list[str], start_date: date, end_date: date
    ) -> tuple[list[RawData], list[tuple[str, str]]]:
        if self.alarm_collector is None:
            raise RuntimeError("Alarm collector is not configured")
        collected, failures = self.alarm_collector.collect_history_devices(
            device_dns, start_date, end_date
        )
        for raw_data in collected:
            self.storage.save_rawdata(raw_data)
        return collected, failures

    def check_energy_balance_quality(
        self, start_date: date, end_date: date
    ) -> dict[str, object]:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        if self.energy_balance_record_builder is None:
            raise RuntimeError("Energy-balance record builder is not configured")
        raw_items = self.storage.load_rawdata_for_range(
            "fusionsolar_energy_balance", start_date, end_date
        )
        issues = []
        valid_counts = Counter()
        missing_markers = Counter()
        for raw_data in raw_items:
            try:
                records = self.energy_balance_record_builder.build(raw_data)
            except ValueError as error:
                issues.append(
                    {"target_date": raw_data.target_date.isoformat(), "error": str(error)}
                )
                continue
            data = raw_data.payload["data"]
            for metric in self.energy_balance_record_builder.SERIES:
                values = data[metric]
                missing_markers[metric] += sum(
                    value == "--" or value is None for value in values
                )
                valid_counts[metric] += sum(
                    record.metric == metric for record in records
                )
            missing_daily = [
                metric
                for metric in self.energy_balance_record_builder.DAILY
                if metric not in data
            ]
            if missing_daily:
                issues.append(
                    {
                        "target_date": raw_data.target_date.isoformat(),
                        "error": "missing daily values: " + ", ".join(missing_daily),
                    }
                )
        raw_dates = {item.target_date for item in raw_items}
        record_dates = self.storage.get_record_dates(
            "fusionsolar_energy_balance", start_date, end_date
        )
        return {
            "raw_data_count": len(raw_items),
            "issues": issues,
            "missing_markers_by_series": dict(missing_markers),
            "valid_values_by_series": dict(valid_counts),
            "raw_data_without_records": sorted(
                value.isoformat() for value in raw_dates - record_dates if value
            ),
        }

    def diagnose_device_realtime(self) -> dict[str, object]:
        items = [
            item
            for item in self.storage.load_rawdata()
            if item.source == "fusionsolar_device_realtime"
        ]
        by_device = Counter(
            str((item.metadata or {}).get("device_dn", "unknown"))
            for item in items
        )
        latest = {}
        gaps = Counter()
        timestamps = {}
        for item in items:
            device_dn = str((item.metadata or {}).get("device_dn", "unknown"))
            timestamps.setdefault(device_dn, []).append(item.timestamp)
            if device_dn not in latest or item.timestamp > latest[device_dn]:
                latest[device_dn] = item.timestamp
        for device_dn, values in timestamps.items():
            ordered = sorted(set(values))
            gaps[device_dn] = sum(
                (current - previous).total_seconds() > 600
                for previous, current in zip(ordered, ordered[1:])
            )
        return {
            "collection_count": len(items),
            "by_device": dict(sorted(by_device.items())),
            "latest_by_device": {
                key: value.isoformat() for key, value in sorted(latest.items())
            },
            "large_gaps_by_device": dict(sorted(gaps.items())),
            "api_failure_count": None,
        }

    def diagnose_battery_dc(self) -> dict[str, object]:
        items = [
            item
            for item in self.storage.load_rawdata()
            if item.source == "fusionsolar_battery_dc"
        ]
        by_module = Counter()
        latest_by_module = {}
        empty_responses = Counter()
        invalid_responses = 0
        for item in items:
            module_id = str((item.metadata or {}).get("module_id", "unknown"))
            by_module[module_id] += 1
            previous = latest_by_module.get(module_id)
            if previous is None or item.timestamp > previous:
                latest_by_module[module_id] = item.timestamp
            data = item.payload.get("data")
            if not isinstance(item.payload.get("success"), bool) or not isinstance(
                data, list
            ):
                invalid_responses += 1
            elif not data:
                empty_responses[module_id] += 1
        return {
            "collection_count": len(items),
            "by_module": dict(sorted(by_module.items())),
            "latest_by_module": {
                key: value.isoformat()
                for key, value in sorted(latest_by_module.items())
            },
            "empty_responses_by_module": dict(
                sorted(empty_responses.items())
            ),
            "invalid_responses": invalid_responses,
        }

    def check_battery_dc_quality(self) -> dict[str, object]:
        diagnosis = self.diagnose_battery_dc()
        modules = diagnosis["by_module"]
        assert isinstance(modules, dict)
        missing_modules = [
            module_id for module_id in ("1", "2", "3", "4") if module_id not in modules
        ]
        issues = int(diagnosis["invalid_responses"])
        if diagnosis["collection_count"] == 0:
            issues += 1
        issues += len(missing_modules)
        return {
            **diagnosis,
            "missing_modules": missing_modules,
            "issue_count": issues,
        }

    def diagnose_alarms(self) -> dict[str, object]:
        items = [
            item
            for item in self.storage.load_rawdata()
            if item.source
            in {"fusionsolar_alarm_current", "fusionsolar_alarm_history"}
        ]
        by_source = Counter()
        by_device = Counter()
        latest_current_by_device = {}
        invalid_responses = 0
        non_success_responses = 0
        total_hits = 0
        for item in items:
            by_source[item.source] += 1
            device_dn = str((item.metadata or {}).get("device_dn", "unknown"))
            by_device[device_dn] += 1
            if item.source == "fusionsolar_alarm_current":
                previous = latest_current_by_device.get(device_dn)
                if previous is None or item.timestamp > previous:
                    latest_current_by_device[device_dn] = item.timestamp
            if item.payload.get("success") is not True:
                non_success_responses += 1
            data = item.payload.get("data")
            if not isinstance(data, dict) or not isinstance(
                data.get("hits"), list
            ):
                invalid_responses += 1
            else:
                total_hits += len(data["hits"])
        return {
            "collection_count": len(items),
            "by_source": dict(sorted(by_source.items())),
            "by_device": dict(sorted(by_device.items())),
            "latest_current_by_device": {
                key: value.isoformat()
                for key, value in sorted(latest_current_by_device.items())
            },
            "total_hits": total_hits,
            "invalid_responses": invalid_responses,
            "non_success_responses": non_success_responses,
        }

    def check_alarm_quality(
        self, expected_device_dns: list[str]
    ) -> dict[str, object]:
        diagnosis = self.diagnose_alarms()
        latest = diagnosis["latest_current_by_device"]
        assert isinstance(latest, dict)
        missing_current_devices = [
            device_dn
            for device_dn in expected_device_dns
            if device_dn not in latest
        ]
        issue_count = (
            int(diagnosis["invalid_responses"])
            + int(diagnosis["non_success_responses"])
            + len(missing_current_devices)
        )
        return {
            **diagnosis,
            "missing_current_devices": missing_current_devices,
            "issue_count": issue_count,
        }

    def find_missing_dates(
        self, start_date: date, end_date: date
    ) -> list[date]:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        existing_dates = self.storage.get_record_dates(
            source="fusionsolar",
            start_date=start_date,
            end_date=end_date,
            timezone_name="Asia/Tokyo",
        )
        existing_dates |= self.storage.get_collected_dates(
            source="fusionsolar",
            start_date=start_date,
            end_date=end_date,
        )
        missing_dates = []
        target_date = start_date
        while target_date <= end_date:
            if target_date not in existing_dates:
                missing_dates.append(target_date)
            target_date += timedelta(days=1)
        return missing_dates

    def backfill_missing(
        self, start_date: date, end_date: date
    ) -> list[RawData]:
        raw_data_list = []
        for target_date in self.find_missing_dates(start_date, end_date):
            raw_data = self.collector.collect_for_date(target_date)
            self.storage.save_rawdata(raw_data)
            records = self.record_builder.build(raw_data)
            self.storage.save_records(records)
            raw_data_list.append(raw_data)
        return raw_data_list

    def check_quality(
        self, start_date: date, end_date: date
    ) -> dict[str, object]:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        records = self.storage.load_records_for_range(
            source="fusionsolar",
            start_date=start_date,
            end_date=end_date,
            timezone_name="Asia/Tokyo",
        )
        duplicate_records = 0
        invalid_values = 0
        unexpected_metric_names = set()
        unexpected_units = 0
        seen_records = set()
        records_by_timestamp = {}
        for record in records:
            record_key = (
                record.source,
                record.timestamp,
                record.metric,
                _hashable_value(record.value),
                record.unit,
            )
            if record_key in seen_records:
                duplicate_records += 1
            else:
                seen_records.add(record_key)
            if (
                type(record.value) not in (int, float)
                and record.value is not None
                or isinstance(record.value, float)
                and not math.isfinite(record.value)
            ):
                invalid_values += 1
            if record.metric not in self.QUALITY_UNITS:
                unexpected_metric_names.add(record.metric)
            if self.QUALITY_UNITS.get(record.metric) != record.unit:
                unexpected_units += 1
            records_by_timestamp.setdefault(record.timestamp, set()).add(
                record.metric
            )
        unexpected_metrics = sorted(unexpected_metric_names)
        timestamps = sorted(records_by_timestamp)
        expected_metrics = self.REQUIRED_QUALITY_METRICS
        missing_metric_points = [
            {
                "timestamp": timestamp.isoformat(),
                "missing_metrics": sorted(
                    expected_metrics - records_by_timestamp[timestamp]
                ),
            }
            for timestamp in timestamps
            if expected_metrics - records_by_timestamp[timestamp]
        ]

        timezone = ZoneInfo("Asia/Tokyo")
        irregular_intervals = []
        for previous, current in zip(timestamps, timestamps[1:]):
            minutes = (current - previous).total_seconds() / 60
            if (
                previous.astimezone(timezone).date()
                == current.astimezone(timezone).date()
                and minutes != self.EXPECTED_INTERVAL_MINUTES
            ):
                irregular_intervals.append(
                    {
                        "previous": previous.isoformat(),
                        "current": current.isoformat(),
                        "minutes": minutes,
                    }
                )

        return {
            "duplicate_records": duplicate_records,
            "invalid_values": invalid_values,
            "unexpected_metrics": unexpected_metrics,
            "unexpected_units": unexpected_units,
            "missing_metric_points": missing_metric_points,
            "irregular_intervals": irregular_intervals,
            "summary": {
                "record_count": len(records),
                "timestamp_count": len(timestamps),
                "first_timestamp": (
                    timestamps[0].isoformat() if timestamps else None
                ),
                "last_timestamp": (
                    timestamps[-1].isoformat() if timestamps else None
                ),
            },
        }

    def diagnose_quality(
        self, start_date: date, end_date: date
    ) -> dict[str, object]:
        quality = self.check_quality(start_date, end_date)
        timezone = ZoneInfo("Asia/Tokyo")

        missing_by_metric = Counter()
        missing_combinations = Counter()
        missing_by_hour = Counter()
        missing_by_month = Counter()
        missing_points = quality["missing_metric_points"]
        assert isinstance(missing_points, list)
        for point in missing_points:
            missing_metrics = tuple(point["missing_metrics"])
            missing_by_metric.update(missing_metrics)
            missing_combinations[missing_metrics] += 1
            timestamp = datetime.fromisoformat(point["timestamp"]).astimezone(
                timezone
            )
            missing_by_hour[str(timestamp.hour)] += 1
            missing_by_month[timestamp.strftime("%Y-%m")] += 1

        intervals_by_minutes = Counter()
        intervals_shorter_than_five = 0
        intervals_longer_than_five = 0
        intervals_by_hour = Counter()
        intervals_by_month = Counter()
        irregular_intervals = quality["irregular_intervals"]
        assert isinstance(irregular_intervals, list)
        for interval in irregular_intervals:
            minutes = interval["minutes"]
            intervals_by_minutes[minutes] += 1
            if minutes < 5:
                intervals_shorter_than_five += 1
            else:
                intervals_longer_than_five += 1
            current = datetime.fromisoformat(interval["current"]).astimezone(
                timezone
            )
            intervals_by_hour[str(current.hour)] += 1
            intervals_by_month[current.strftime("%Y-%m")] += 1

        return {
            "missing_metrics_by_metric": dict(sorted(missing_by_metric.items())),
            "missing_combinations": [
                {"missing_metrics": list(metrics), "count": count}
                for metrics, count in sorted(
                    missing_combinations.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ],
            "missing_by_hour": _sorted_hour_counts(missing_by_hour),
            "missing_by_month": dict(sorted(missing_by_month.items())),
            "missing_examples": missing_points[:20],
            "irregular_intervals_by_minutes": dict(
                sorted(intervals_by_minutes.items())
            ),
            "irregular_intervals_shorter_than_5_minutes": (
                intervals_shorter_than_five
            ),
            "irregular_intervals_longer_than_5_minutes": (
                intervals_longer_than_five
            ),
            "irregular_intervals_by_hour": _sorted_hour_counts(
                intervals_by_hour
            ),
            "irregular_intervals_by_month": dict(
                sorted(intervals_by_month.items())
            ),
            "irregular_interval_examples": irregular_intervals[:20],
        }


def _hashable_value(value: object) -> object:
    if isinstance(value, list):
        return (list, tuple(_hashable_value(item) for item in value))
    if isinstance(value, dict):
        return (
            dict,
            frozenset(
                (key, _hashable_value(item)) for key, item in value.items()
            ),
        )
    return value


def _sorted_hour_counts(counts: Counter) -> dict[str, int]:
    return dict(sorted(counts.items(), key=lambda item: int(item[0])))
