from hedp.application import Application
from hedp.configuration import Configuration
from hedp.fusionsolar_client import FusionSolarClient
from hedp.fusionsolar_collector import FusionSolarCollector
from hedp.fusionsolar_record_builder import FusionSolarRecordBuilder
from hedp.raw_data import RawData
from hedp.storage import Storage


def main() -> RawData:
    configuration = Configuration.from_environment()
    client = FusionSolarClient(
        base_url=configuration.base_url,
        station_dn=configuration.station_dn,
        username=configuration.username,
        password=configuration.password,
    )
    collector = FusionSolarCollector(client)
    record_builder = FusionSolarRecordBuilder()
    storage = Storage(configuration.database_path)
    connection = storage.connect()
    try:
        application = Application(collector, storage, record_builder)
        return application.run()
    finally:
        connection.close()


if __name__ == "__main__":
    main()
