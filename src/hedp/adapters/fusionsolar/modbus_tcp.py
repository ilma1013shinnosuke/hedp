from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import socket
import struct
from typing import Callable


class ModbusTcpError(RuntimeError):
    """A safe Modbus TCP error that does not contain addresses or payloads."""


@dataclass(frozen=True)
class ModbusReadResult:
    function_code: int
    start_address: int
    registers: tuple[int, ...]


class ReadOnlyModbusTcpClient:
    """Minimal Modbus TCP client that intentionally implements no writes."""

    _READ_FUNCTIONS = {3, 4}

    def __init__(
        self,
        host: str,
        *,
        port: int = 502,
        unit_id: int = 0,
        timeout_seconds: float = 3.0,
        connection_factory: Callable[..., socket.socket] = socket.create_connection,
    ) -> None:
        if not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if not 0 <= unit_id <= 255:
            raise ValueError("unit_id must be between 0 and 255")
        if not 0 < timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be greater than 0 and at most 30")
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.timeout_seconds = timeout_seconds
        self._connection_factory = connection_factory
        self._transaction_id = 0

    def read_holding_registers(
        self, start_address: int, count: int
    ) -> ModbusReadResult:
        return self._read_registers(3, start_address, count)

    def read_input_registers(
        self, start_address: int, count: int
    ) -> ModbusReadResult:
        return self._read_registers(4, start_address, count)

    def _read_registers(
        self, function_code: int, start_address: int, count: int
    ) -> ModbusReadResult:
        if function_code not in self._READ_FUNCTIONS:
            raise ValueError("only Modbus read functions 3 and 4 are permitted")
        if not 0 <= start_address <= 65535:
            raise ValueError("start_address must be between 0 and 65535")
        if not 1 <= count <= 125:
            raise ValueError("count must be between 1 and 125")
        if start_address + count > 65536:
            raise ValueError("requested register range exceeds the address space")

        self._require_private_target()
        self._transaction_id = (self._transaction_id % 65535) + 1
        request_pdu = struct.pack(">BHH", function_code, start_address, count)
        request = struct.pack(
            ">HHHB",
            self._transaction_id,
            0,
            len(request_pdu) + 1,
            self.unit_id,
        ) + request_pdu

        try:
            with self._connection_factory(
                (self.host, self.port), self.timeout_seconds
            ) as connection:
                connection.settimeout(self.timeout_seconds)
                connection.sendall(request)
                header = self._receive_exact(connection, 7)
                transaction_id, protocol_id, length, unit_id = struct.unpack(
                    ">HHHB", header
                )
                if not 2 <= length <= 254:
                    raise ModbusTcpError("invalid Modbus response length")
                response_pdu = self._receive_exact(connection, length - 1)
        except ModbusTcpError:
            raise
        except (OSError, TimeoutError) as error:
            raise ModbusTcpError("Modbus target is unavailable") from error

        if transaction_id != self._transaction_id:
            raise ModbusTcpError("Modbus transaction ID does not match")
        if protocol_id != 0:
            raise ModbusTcpError("unexpected Modbus protocol ID")
        if unit_id != self.unit_id:
            raise ModbusTcpError("Modbus unit ID does not match")
        if not response_pdu:
            raise ModbusTcpError("empty Modbus response")

        response_function = response_pdu[0]
        if response_function == function_code | 0x80:
            raise ModbusTcpError("Modbus device returned an exception")
        if response_function != function_code:
            raise ModbusTcpError("unexpected Modbus function code")
        if len(response_pdu) < 2:
            raise ModbusTcpError("truncated Modbus response")
        byte_count = response_pdu[1]
        expected_bytes = count * 2
        if byte_count != expected_bytes or len(response_pdu) != byte_count + 2:
            raise ModbusTcpError("Modbus register count does not match")
        registers = struct.unpack(f">{count}H", response_pdu[2:])
        return ModbusReadResult(
            function_code=function_code,
            start_address=start_address,
            registers=tuple(registers),
        )

    def _require_private_target(self) -> None:
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(
                    self.host,
                    self.port,
                    type=socket.SOCK_STREAM,
                )
            }
        except OSError as error:
            raise ModbusTcpError("Modbus target name cannot be resolved") from error
        if not addresses:
            raise ModbusTcpError("Modbus target name cannot be resolved")
        for address in addresses:
            parsed = ipaddress.ip_address(address)
            if not (parsed.is_private or parsed.is_link_local):
                raise ModbusTcpError(
                    "Modbus target must be on a private or link-local network"
                )

    @staticmethod
    def _receive_exact(connection: socket.socket, size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            chunk = connection.recv(size - len(chunks))
            if not chunk:
                raise ModbusTcpError("Modbus connection closed early")
            chunks.extend(chunk)
        return bytes(chunks)
