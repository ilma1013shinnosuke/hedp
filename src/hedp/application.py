from datetime import date

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
