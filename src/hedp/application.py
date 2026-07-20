from hedp.fusionsolar_collector import FusionSolarCollector
from hedp.raw_data import RawData
from hedp.storage import Storage


class Application:
    def __init__(
        self, collector: FusionSolarCollector, storage: Storage
    ) -> None:
        self.collector = collector
        self.storage = storage

    def run(self) -> RawData:
        raw_data = self.collector.collect()
        self.storage.save_rawdata(raw_data)
        return raw_data
