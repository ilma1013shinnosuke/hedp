from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from hedp.adapters.fusionsolar.client import FusionSolarClient
from hedp.raw_data import RawData


class FusionSolarEnergyBalanceCollector:
    ENDPOINT = "/rest/pvms/web/station/v1/overview/energy-balance"

    def __init__(self, client: FusionSolarClient) -> None:
        self.client = client

    def collect_for_date(self, target_date: date) -> RawData:
        tokyo = ZoneInfo("Asia/Tokyo")
        target_midnight = datetime.combine(target_date, time.min, tzinfo=tokyo)
        request_time = datetime.now(timezone.utc)
        query = urlencode(
            {
                "stationDn": self.client.station_dn,
                "timeDim": "2",
                "queryTime": int(target_midnight.timestamp() * 1000),
                "timeZone": "9",
                "timeZoneStr": "Asia/Tokyo",
                "dateStr": f"{target_date.isoformat()} 00:00:00",
                "_": int(request_time.timestamp() * 1000),
            }
        )
        payload = self.client.get_json(f"{self.ENDPOINT}?{query}")
        return RawData(
            source="fusionsolar_energy_balance",
            timestamp=datetime.now(timezone.utc),
            payload=payload,
            target_date=target_date,
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
