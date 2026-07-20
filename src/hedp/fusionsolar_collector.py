from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from hedp.fusionsolar_client import FusionSolarClient
from hedp.raw_data import RawData


class FusionSolarCollector:
    def __init__(self, client: FusionSolarClient) -> None:
        self.client = client

    def collect(self) -> RawData:
        tokyo = ZoneInfo("Asia/Tokyo")
        today = datetime.now(tokyo).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        stat_time = int(today.timestamp() * 1000)
        payload = self.client.post_json(
            "/rest/pvms/web/report/v1/station/station-kpi-list",
            {
                "currencyUnit": "¥",
                "counterIDs": [
                    "productPower",
                    "inverterPower",
                    "onGridPower",
                    "buyPower",
                    "powerProfit",
                ],
                "moList": [
                    {
                        "moType": 20801,
                        "moString": self.client.station_dn,
                    }
                ],
                "orderBy": "fmtCollectTimeStr",
                "page": 1,
                "pageSize": 100,
                "sort": "asc",
                "statDim": "2",
                "statTime": stat_time,
                "statType": "1",
                "station": "1",
                "timeZone": 9,
                "timeZoneStr": "Asia/Tokyo",
            },
        )
        return RawData(
            source="fusionsolar",
            timestamp=datetime.now(timezone.utc),
            payload=payload,
        )
