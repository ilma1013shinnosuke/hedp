from __future__ import annotations

import socket

import pytest

from hedp.adapters.ecocute import (
    EchonetResponseError,
    EchonetTransportError,
    EcoCuteReadOnlyUdpTransport,
)


def _response(transaction_id: int, *, service: int = 0x72) -> bytes:
    return (
        b"\x10\x81"
        + transaction_id.to_bytes(2, "big")
        + b"\x02\x6b\x01\x05\xff\x01"
        + bytes((service, 1, 0x80, 1, 0x30))
    )


class FakeSocket:
    def __init__(self, datagrams: list[tuple[bytes, tuple[str, int]]]) -> None:
        self.datagrams = iter(datagrams)
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.closed = False

    def settimeout(self, value: float) -> None:
        assert value > 0

    def sendto(self, value: bytes, target: tuple[str, int]) -> None:
        self.sent.append((value, target))

    def recvfrom(self, maximum: int) -> tuple[bytes, tuple[str, int]]:
        assert maximum == 65_535
        return next(self.datagrams)

    def close(self) -> None:
        self.closed = True


def test_transport_can_only_send_get_and_matches_the_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeSocket(
        [
            (_response(7), ("192.168.1.99", 3610)),
            (_response(8), ("192.168.1.20", 3610)),
            (_response(7), ("192.168.1.20", 3610)),
        ]
    )
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("192.168.1.20", 3610))
        ],
    )
    transport = EcoCuteReadOnlyUdpTransport(
        "water-heater.local",
        socket_factory=lambda *args: fake,  # type: ignore[arg-type]
    )

    exchange = transport.get(transaction_id=7, epcs=(0x80,))

    assert exchange.frame.transaction_id == 7
    assert fake.sent[0][0][10] == 0x62
    assert fake.sent[0][1] == ("192.168.1.20", 3610)
    assert fake.closed


def test_transport_rejects_non_private_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("8.8.8.8", 3610))
        ],
    )
    transport = EcoCuteReadOnlyUdpTransport("example.invalid")

    with pytest.raises(EchonetTransportError, match="private network"):
        transport.get(transaction_id=1, epcs=(0x80,))


def test_transport_reports_get_sna_without_packet_contents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeSocket([(_response(1, service=0x52), ("192.168.1.20", 3610))])
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("192.168.1.20", 3610))
        ],
    )
    transport = EcoCuteReadOnlyUdpTransport(
        "water-heater.local",
        socket_factory=lambda *args: fake,  # type: ignore[arg-type]
    )

    with pytest.raises(EchonetResponseError) as caught:
        transport.get(transaction_id=1, epcs=(0x80,))

    assert "192.168" not in str(caught.value)
    assert "1081" not in str(caught.value)
