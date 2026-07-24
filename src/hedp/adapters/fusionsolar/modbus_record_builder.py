from __future__ import annotations

from hedp.adapters.fusionsolar.modbus_profiles import decode_sun2000_jpl1
from hedp.storage import RawData, Record


class FusionSolarModbusRecordBuilder:
    """Build confirmed numeric JPL1 metrics from preserved register words."""

    METRICS = {
        "input_power_kw": ("input_power", "kW"),
        "active_power_kw": ("active_power", "kW"),
        "grid_frequency_hz": ("grid_frequency", "Hz"),
        "internal_temperature_c": ("internal_temperature", "C"),
        "device_status_code": ("device_status", "code"),
        "total_yield_kwh": ("total_yield", "kWh"),
        "daily_yield_kwh": ("daily_yield", "kWh"),
        "storage_status_code": ("storage_status", "code"),
        "storage_power_kw": ("storage_power", "kW"),
        "storage_soc_percent": ("storage_soc", "%"),
    }

    def build(self, raw_data: RawData) -> list[Record]:
        if raw_data.source != "fusionsolar_modbus_tcp":
            raise ValueError("unexpected RawData source")
        ranges = raw_data.payload.get("ranges")
        if not isinstance(ranges, list):
            raise ValueError("Modbus RawData ranges are missing")
        snapshot = decode_sun2000_jpl1(ranges)
        return [
            Record(
                source=raw_data.source,
                timestamp=raw_data.timestamp,
                metric=metric,
                value=snapshot[field],
                unit=unit,
            )
            for field, (metric, unit) in self.METRICS.items()
        ]
