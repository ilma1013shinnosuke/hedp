from datetime import date, timedelta

from hedp.fusionsolar_collector import FusionSolarCollector
from hedp.fusionsolar_record_builder import FusionSolarRecordBuilder
from hedp.raw_data import RawData
from hedp.storage import Storage


class Application:
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
