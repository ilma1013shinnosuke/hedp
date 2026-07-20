from collections import Counter
from datetime import date, timedelta
from datetime import datetime
import math
from zoneinfo import ZoneInfo

from hedp.fusionsolar_collector import FusionSolarCollector
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
        collector: FusionSolarCollector,
        storage: Storage,
        record_builder: FusionSolarRecordBuilder,
    ) -> None:
        self.collector = collector
        self.storage = storage
        self.record_builder = record_builder

    def run(self) -> RawData:
        raw_data = self.collector.collect()
        self.storage.save_rawdata(raw_data)
        records = self.record_builder.build(raw_data)
        self.storage.save_records(records)
        return raw_data

    def run_range(
        self, start_date: date, end_date: date
    ) -> list[RawData]:
        raw_data_list = self.collector.collect_range(start_date, end_date)
        for raw_data in raw_data_list:
            self.storage.save_rawdata(raw_data)
            records = self.record_builder.build(raw_data)
            self.storage.save_records(records)
        return raw_data_list

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
