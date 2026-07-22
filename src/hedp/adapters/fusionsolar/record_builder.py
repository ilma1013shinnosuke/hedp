from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from hedp.raw_data import RawData
from hedp.record import Record


class FusionSolarRecordBuilder:
    _METRIC_UNITS = {
        "productPower": "kW",
        "inverterPower": "kW",
        "onGridPower": "kW",
        "buyPower": "kW",
        "powerProfit": "JPY",
    }

    def build(self, raw_data: RawData) -> list[Record]:
        data = raw_data.payload.get("data")
        if not isinstance(data, dict):
            return []
        rows = data.get("list")
        if not isinstance(rows, list):
            return []

        records = []
        tokyo = ZoneInfo("Asia/Tokyo")
        for row in rows:
            if not isinstance(row, dict):
                continue
            collected_at = row.get("fmtCollectTimeStr")
            if not isinstance(collected_at, str):
                continue
            timestamp = (
                datetime.fromisoformat(collected_at)
                .replace(tzinfo=tokyo)
                .astimezone(timezone.utc)
            )
            for metric, unit in self._METRIC_UNITS.items():
                if metric not in row:
                    continue
                records.append(
                    Record(
                        source=raw_data.source,
                        timestamp=timestamp,
                        metric=metric,
                        value=row[metric],
                        unit=unit,
                    )
                )
        return records
