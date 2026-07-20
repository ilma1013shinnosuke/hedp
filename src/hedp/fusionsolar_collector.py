from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from hedp.fusionsolar_client import FusionSolarClient
from hedp.raw_data import RawData


class FusionSolarCollector:
    def __init__(self, client: FusionSolarClient) -> None:
        self.client = client

    def collect(self) -> RawData:
        tokyo = ZoneInfo("Asia/Tokyo")
        return self.collect_for_date(datetime.now(tokyo).date())

    def collect_for_date(self, target_date: date) -> RawData:
        tokyo = ZoneInfo("Asia/Tokyo")
        target_midnight = datetime.combine(target_date, time.min, tzinfo=tokyo)
        stat_time = int(target_midnight.timestamp() * 1000)
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

    def collect_range(
        self, start_date: date, end_date: date
    ) -> list[RawData]:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        results = []
        target_date = start_date
        while target_date <= end_date:
            results.append(self.collect_for_date(target_date))
            target_date += timedelta(days=1)
        return results
