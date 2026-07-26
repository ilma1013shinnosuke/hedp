from __future__ import annotations

import json

import pytest

from hedp.adapters.smartledz import (
    SmartLedzTcpReadTransport,
    SmartLedzTransportError,
    group_list,
)
from hedp.adapters.smartledz.framing import decode_frame, encode_frames


class FakeSocket:
    def __init__(self, response: bytes) -> None:
        self.response = bytearray(response)
        self.sent = bytearray()
        self.timeout = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def settimeout(self, value):
        self.timeout = value

    def sendall(self, value):
        self.sent.extend(value)

    def recv(self, length):
        value = bytes(self.response[:length])
        del self.response[:length]
        return value


def test_tcp_transport_sends_only_read_command_and_correlates_response() -> None:
    response = encode_frames(b'{"ErrorCode":0,"Result":[]}', request_id=0)[0]
    connection = FakeSocket(response)
    transport = SmartLedzTcpReadTransport(
        "fixture.invalid", 1234, timeout_seconds=3, connect=lambda *_: connection
    )

    assert transport.read(group_list(gateway_id=11))["ErrorCode"] == 0
    sent = decode_frame(bytes(connection.sent))
    assert json.loads(sent.payload) == {"c": "GroupList", "gateway_id": 11}
    assert connection.timeout == 3


def test_tcp_transport_rejects_unbounded_timeout_and_non_read_command() -> None:
    with pytest.raises(ValueError, match="at most 30"):
        SmartLedzTcpReadTransport("fixture.invalid", 1234, timeout_seconds=31)
    transport = SmartLedzTcpReadTransport("fixture.invalid", 1234)
    with pytest.raises(TypeError, match="confirmed ReadCommand"):
        transport.read(object())


def test_tcp_transport_hides_address_and_invalid_response_details() -> None:
    def unavailable(*_args):
        raise OSError("fixture-household-address")

    failed = SmartLedzTcpReadTransport(
        "fixture-household-address",
        1234,
        connect=unavailable,
    )
    with pytest.raises(SmartLedzTransportError, match="read request failed") as error:
        failed.read(group_list(gateway_id=11))
    assert "fixture-household-address" not in str(error.value)

    response = encode_frames(b"private-not-json", request_id=0)[0]
    invalid = SmartLedzTcpReadTransport(
        "fixture.invalid",
        1234,
        connect=lambda *_args: FakeSocket(response),
    )
    with pytest.raises(SmartLedzTransportError, match="invalid JSON") as invalid_error:
        invalid.read(group_list(gateway_id=11))
    assert "private-not-json" not in str(invalid_error.value)
