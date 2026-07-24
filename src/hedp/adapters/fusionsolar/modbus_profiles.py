from __future__ import annotations

import struct
from typing import Any

from hedp.adapters.fusionsolar.modbus_collector import ModbusRegisterRange


# Confirmed read-only ranges for the SUN2000-4.95KTL-JPL1 at this installation.
# The serial-number range (30015-30024) is intentionally not collected.
SUN2000_JPL1_RANGES = (
    ModbusRegisterRange("identity", 3, 30000, 15),
    ModbusRegisterRange("inverter_realtime", 3, 32064, 52),
    ModbusRegisterRange("storage_realtime", 3, 37000, 5),
)


def decode_sun2000_jpl1(
    ranges: list[dict[str, Any]],
) -> dict[str, Any]:
    """Decode only fields verified against the local JPL1 installation."""
    words = {
        (item["start_address"] + offset): value
        for item in ranges
        for offset, value in enumerate(item["registers"])
    }

    model_bytes = struct.pack(
        ">15H", *(words[address] for address in range(30000, 30015))
    )
    model = (
        model_bytes.split(b"\0", 1)[0]
        .decode("ascii", errors="replace")
        .strip()
    )

    status_code = words[32089]
    return {
        "model": model,
        "input_power_kw": _i32(words, 32064) / 1000,
        "active_power_kw": _i32(words, 32080) / 1000,
        "grid_frequency_hz": words[32085] / 100,
        "internal_temperature_c": _i16(words[32087]) / 10,
        "device_status_code": status_code,
        "device_status": _device_status(status_code),
        "total_yield_kwh": _u32(words, 32106) / 100,
        "daily_yield_kwh": _u32(words, 32114) / 100,
        "storage_status_code": words[37000],
        "storage_power_kw": _i32(words, 37001) / 1000,
        "storage_soc_percent": words[37004] / 10,
    }


def _u32(words: dict[int, int], address: int) -> int:
    return (words[address] << 16) | words[address + 1]


def _i32(words: dict[int, int], address: int) -> int:
    return struct.unpack(
        ">i", struct.pack(">HH", words[address], words[address + 1])
    )[0]


def _i16(value: int) -> int:
    return value - 65536 if value >= 32768 else value


def _device_status(value: int) -> str:
    return {
        0x0000: "standby_initializing",
        0x0001: "standby_insulation_detection",
        0x0002: "standby_irradiation_detection",
        0x0100: "starting",
        0x0200: "on_grid",
        0x0201: "on_grid_power_limited",
        0x0202: "on_grid_self_derating",
        0x0300: "shutdown_fault",
        0x0301: "shutdown_command",
        0x0303: "shutdown_communication_disconnected",
        0xA000: "standby_no_irradiation",
    }.get(value, "unknown")
