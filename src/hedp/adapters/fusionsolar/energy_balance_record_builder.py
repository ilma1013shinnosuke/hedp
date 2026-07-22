from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from hedp.raw_data import RawData
from hedp.record import Record


class FusionSolarEnergyBalanceRecordBuilder:
    SERIES = (
        "productPower", "dieselProductPower", "mainsUsePower", "onGridPower",
        "disGridPower", "usePower", "selfUsePower", "chargePower",
        "dischargePower", "radiationDosePower",
    )
    DAILY = (
        "totalProductPower", "totalSelfUsePower", "totalOnGridPower",
        "totalBuyPower", "totalUsePower", "selfProvide", "onGridPowerRatio",
        "selfUsePowerRatioByProduct", "buyPowerRatio", "selfUsePowerRatioByUse",
    )

    def build(self, raw_data: RawData) -> list[Record]:
        data = raw_data.payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("energy-balance payload data must be an object")
        x_axis = data.get("xAxis")
        if not isinstance(x_axis, list) or len(x_axis) != 288:
            raise ValueError("energy-balance xAxis must contain 288 points")
        for metric in self.SERIES:
            values = data.get(metric)
            if not isinstance(values, list) or len(values) != len(x_axis):
                raise ValueError(f"energy-balance {metric} length does not match xAxis")
        if raw_data.target_date is None:
            raise ValueError("energy-balance RawData requires target_date")

        tokyo = ZoneInfo("Asia/Tokyo")
        timestamps = []
        for value in x_axis:
            if not isinstance(value, str):
                raise ValueError("energy-balance xAxis values must be strings")
            parsed = datetime.fromisoformat(value).replace(tzinfo=tokyo)
            if parsed.date() != raw_data.target_date:
                raise ValueError("energy-balance xAxis date does not match target_date")
            timestamps.append(parsed.astimezone(timezone.utc))
        for previous, current in zip(timestamps, timestamps[1:]):
            if (current - previous).total_seconds() != 300:
                raise ValueError("energy-balance xAxis must be strictly five-minute intervals")

        records = []
        for metric in self.SERIES:
            for timestamp, value in zip(timestamps, data[metric]):
                number = self._number(value)
                if number is not None:
                    records.append(Record(raw_data.source, timestamp, metric, number, "unknown"))
        daily_timestamp = datetime.combine(raw_data.target_date, time.min, tokyo).astimezone(timezone.utc)
        for metric in self.DAILY:
            number = self._number(data.get(metric))
            if number is not None:
                records.append(Record(raw_data.source, daily_timestamp, metric, number, "unknown"))
        return records

    @staticmethod
    def _number(value: object) -> int | float | None:
        if value is None or value == "--" or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None
