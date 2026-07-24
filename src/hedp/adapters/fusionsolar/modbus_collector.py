from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from hedp.adapters.fusionsolar.modbus_tcp import ReadOnlyModbusTcpClient
from hedp.storage import RawData


@dataclass(frozen=True)
class ModbusRegisterRange:
    name: str
    function_code: int
    start_address: int
    count: int

    def __post_init__(self) -> None:
        if not self.name or not self.name.replace("_", "").isalnum():
            raise ValueError("name must use letters, numbers, and underscores")
        if self.function_code not in {3, 4}:
            raise ValueError("only read function codes 3 and 4 are permitted")
        if not 0 <= self.start_address <= 65535:
            raise ValueError("start_address must be between 0 and 65535")
        if not 1 <= self.count <= 125:
            raise ValueError("count must be between 1 and 125")
        if self.start_address + self.count > 65536:
            raise ValueError("register range exceeds the address space")


class FusionSolarModbusCollector:
    """Preserve explicitly approved read-only register ranges as RawData."""

    def __init__(
        self,
        client: ReadOnlyModbusTcpClient,
        *,
        target_alias: str,
        register_ranges: tuple[ModbusRegisterRange, ...],
    ) -> None:
        if not target_alias:
            raise ValueError("target_alias must not be empty")
        if not register_ranges:
            raise ValueError("at least one register range is required")
        self.client = client
        self.target_alias = target_alias
        self.register_ranges = register_ranges

    def collect(self) -> RawData:
        ranges = []
        for definition in self.register_ranges:
            if definition.function_code == 3:
                result = self.client.read_holding_registers(
                    definition.start_address, definition.count
                )
            else:
                result = self.client.read_input_registers(
                    definition.start_address, definition.count
                )
            ranges.append(
                {
                    "name": definition.name,
                    "function_code": result.function_code,
                    "start_address": result.start_address,
                    "registers": list(result.registers),
                }
            )
        return RawData(
            source="fusionsolar_modbus_tcp",
            timestamp=datetime.now(timezone.utc),
            payload={"ranges": ranges},
            metadata={"target_alias": self.target_alias},
        )
