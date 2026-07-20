from datetime import datetime, timezone
from urllib.parse import urlencode

from hedp.fusionsolar_client import FusionSolarClient
from hedp.raw_data import RawData


class FusionSolarCollector:
    def __init__(self, client: FusionSolarClient) -> None:
        self.client = client

    def collect(self) -> RawData:
        query = urlencode({"stationDn": self.client.station_dn})
        payload = self.client.get_json(
            f"/rest/pvms/web/station/v1/station-kpi-list?{query}"
        )
        return RawData(
            source="fusionsolar",
            timestamp=datetime.now(timezone.utc),
            payload=payload,
        )
