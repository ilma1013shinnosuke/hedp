from datetime import date, timedelta
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
        duplicate_records = sum(
            record in records[:index]
            for index, record in enumerate(records)
        )
        invalid_values = sum(
            type(record.value) not in (int, float)
            and record.value is not None
            or isinstance(record.value, float)
            and not math.isfinite(record.value)
            for record in records
        )
        unexpected_metrics = sorted(
            {record.metric for record in records} - self.QUALITY_UNITS.keys()
        )
        unexpected_units = sum(
            self.QUALITY_UNITS.get(record.metric) != record.unit
            for record in records
        )

        records_by_timestamp = {}
        for record in records:
            records_by_timestamp.setdefault(record.timestamp, set()).add(
                record.metric
            )
        timestamps = sorted(records_by_timestamp)
        expected_metrics = set(self.QUALITY_UNITS)
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
                and minutes != 5
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
