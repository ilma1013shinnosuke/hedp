import socket
import struct
from unittest.mock import patch

import pytest

from hedp.adapters.fusionsolar.modbus_collector import (
    FusionSolarModbusCollector,
    ModbusRegisterRange,
)
from hedp.adapters.fusionsolar.modbus_tcp import (
    ModbusTcpError,
    ModbusTransportError,
    ReadOnlyModbusTcpClient,
)


class FakeConnection:
    def __init__(self, response: bytes) -> None:
        self.response = bytearray(response)
        self.request = b""
        self.timeout = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, request):
        self.request = request

    def recv(self, size):
        chunk = self.response[:size]
        del self.response[:size]
        return bytes(chunk)


def response(function_code=3, registers=(10, 20), transaction_id=1):
    payload = struct.pack(
        f">BB{len(registers)}H",
        function_code,
        len(registers) * 2,
        *registers,
    )
    return (
        struct.pack(">HHHB", transaction_id, 0, len(payload) + 1, 0)
        + payload
    )


@patch(
    "hedp.adapters.fusionsolar.modbus_tcp.socket.getaddrinfo",
    return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.2", 0))],
)
def test_reads_holding_registers_without_exposing_write_functions(_):
    connection = FakeConnection(response())
    client = ReadOnlyModbusTcpClient(
        "inverter.local",
        connection_factory=lambda *_: connection,
    )

    result = client.read_holding_registers(32000, 2)

    assert result.registers == (10, 20)
    assert connection.request[7:] == struct.pack(">BHH", 3, 32000, 2)
    assert not hasattr(client, "write_register")


@patch(
    "hedp.adapters.fusionsolar.modbus_tcp.socket.getaddrinfo",
    return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))],
)
def test_rejects_public_network_targets(_):
    client = ReadOnlyModbusTcpClient(
        "public.example",
        connection_factory=lambda *_: FakeConnection(response()),
    )

    with pytest.raises(ModbusTcpError, match="private or link-local"):
        client.read_holding_registers(1, 1)


def test_collector_preserves_register_words_without_guessing_meaning():
    client = type(
        "Client",
        (),
        {
            "read_holding_registers": lambda self, start, count: type(
                "Result",
                (),
                {
                    "function_code": 3,
                    "start_address": start,
                    "registers": (100, 200),
                },
            )()
        },
    )()
    collector = FusionSolarModbusCollector(
        client,
        target_alias="solar-inverter",
        register_ranges=(
            ModbusRegisterRange("confirmed_range", 3, 32000, 2),
        ),
    )

    raw = collector.collect()

    assert raw.payload["ranges"][0]["registers"] == [100, 200]
    assert raw.metadata == {"target_alias": "solar-inverter"}


@patch(
    "hedp.adapters.fusionsolar.modbus_tcp.socket.getaddrinfo",
    side_effect=OSError("unavailable"),
)
def test_name_resolution_failure_is_a_retryable_transport_error(_):
    client = ReadOnlyModbusTcpClient("inverter.local")

    with pytest.raises(ModbusTransportError):
        client.read_holding_registers(1, 1)


def test_collector_can_attach_opaque_continuity_evidence():
    client = type(
        "Client",
        (),
        {
            "read_holding_registers": lambda self, start, count: type(
                "Result",
                (),
                {
                    "function_code": 3,
                    "start_address": start,
                    "registers": (100, 200),
                },
            )()
        },
    )()
    collector = FusionSolarModbusCollector(
        client,
        target_alias="solar-inverter",
        register_ranges=(ModbusRegisterRange("confirmed_range", 3, 32000, 2),),
        continuity_id="0123456789abcdef0123456789abcdef",
        continuity_reason="scheduling_gap",
    )

    assert collector.collect().metadata == {
        "target_alias": "solar-inverter",
        "continuity_id": "0123456789abcdef0123456789abcdef",
        "continuity_reason": "scheduling_gap",
    }
