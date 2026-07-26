from __future__ import annotations

from datetime import datetime, timedelta, timezone
import socket
from types import SimpleNamespace

import pytest

import hedp.adapters.ecocute as ecocute_read_api
from hedp.adapters.ecocute import (
    EchonetFrame,
    EchonetProperty,
    EchonetResponseError,
    EchonetTransportError,
)
from hedp.adapters.ecocute.echonet import build_set_request
from hedp.adapters.ecocute.operation import (
    DispatchStatus,
    EcoCuteOperationAdapter,
    EcoCuteSetCommand,
    OperationOutcome,
    RuntimeCapabilitySnapshot,
    VerificationStatus,
)
from hedp.adapters.ecocute.transport import EcoCuteSetUdpTransport


NOW = datetime(2026, 7, 26, 1, 2, 3, tzinfo=timezone.utc)


class FakeSetTransport:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, object]] = []

    def set(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return object()


class FakeReadTransport:
    def __init__(self, epc: int, data: bytes) -> None:
        self.epc = epc
        self.data = data
        self.calls: list[dict[str, object]] = []

    def get(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(
            frame=EchonetFrame(
                2,
                bytes((0x02, 0x6B, 0x01)),
                bytes((0x05, 0xFF, 0x01)),
                0x72,
                (EchonetProperty(self.epc, self.data),),
            )
        )


def adapter(
    set_transport: FakeSetTransport,
    read_transport: FakeReadTransport,
    *,
    set_epcs: frozenset[int] = frozenset((0xC7,)),
    get_epcs: frozenset[int] = frozenset((0xC7,)),
    target_alias: str = "main_water_heater",
    observed_at: datetime = NOW,
    now: datetime = NOW,
    delays: list[float] | None = None,
) -> EcoCuteOperationAdapter:
    ids = iter((1, 2))
    return EcoCuteOperationAdapter(
        set_transport,
        read_transport,
        capability_snapshot=RuntimeCapabilitySnapshot(
            target_alias,
            set_epcs,
            get_epcs,
            observed_at,
            timedelta(minutes=5),
        ),
        readback_delay_seconds=1.5,
        sleeper=lambda value: delays.append(value) if delays is not None else None,
        transaction_id_factory=lambda: next(ids),
        now=lambda: now,
    )


def test_read_only_package_does_not_export_operation_adapter() -> None:
    assert not hasattr(ecocute_read_api, "EcoCuteOperationAdapter")


def test_set_builder_produces_one_property_setc_frame() -> None:
    request = build_set_request(
        transaction_id=0x1234,
        epc=0xC7,
        data=b"\x41",
        instance_code=1,
    )
    assert request.hex() == "1081123405ff01026b016101c70141"


def test_operation_dispatches_once_and_verifies_exact_readback() -> None:
    setter = FakeSetTransport()
    reader = FakeReadTransport(0xC7, b"\x41")
    delays: list[float] = []

    result = adapter(setter, reader, delays=delays).execute(
        EcoCuteSetCommand("main_water_heater", 0xC7, b"\x41", b"\x41")
    )

    assert len(setter.calls) == 1
    assert len(reader.calls) == 1
    assert result.dispatch.status is DispatchStatus.ACCEPTED
    assert result.dispatch.attempt_number == 1
    assert result.verification.status is VerificationStatus.MATCHED
    assert result.verification.method == "echonet_lite_get"
    assert result.verification.quality == "good"
    assert result.verification.checked_at == NOW.isoformat()
    assert result.outcome is OperationOutcome.COMPLETED
    assert delays == [1.5]
    assert result.dispatch.__dict__ == {
        "attempted_at": NOW.isoformat(),
        "target_alias": "main_water_heater",
        "epc": 0xC7,
        "status": DispatchStatus.ACCEPTED,
        "attempt_number": 1,
        "transport": "echonet_lite_unicast_udp",
    }


def test_unobserved_set_epc_is_blocked_before_transport() -> None:
    setter = FakeSetTransport()
    reader = FakeReadTransport(0xCA, b"\x00")
    with pytest.raises(PermissionError, match="runtime Set map"):
        adapter(setter, reader).execute(
            EcoCuteSetCommand("main_water_heater", 0xCA, b"\x00", b"\x00")
        )
    assert setter.calls == []
    assert reader.calls == []


def test_snapshot_for_another_target_is_blocked_before_transport() -> None:
    setter = FakeSetTransport()
    reader = FakeReadTransport(0xC7, b"\x41")
    with pytest.raises(PermissionError, match="different target"):
        adapter(setter, reader, target_alias="other_water_heater").execute(
            EcoCuteSetCommand("main_water_heater", 0xC7, b"\x41", b"\x41")
        )
    assert setter.calls == []


def test_stale_snapshot_is_blocked_before_transport() -> None:
    setter = FakeSetTransport()
    reader = FakeReadTransport(0xC7, b"\x41")
    with pytest.raises(PermissionError, match="stale"):
        adapter(
            setter,
            reader,
            observed_at=NOW - timedelta(minutes=6),
        ).execute(
            EcoCuteSetCommand("main_water_heater", 0xC7, b"\x41", b"\x41")
        )
    assert setter.calls == []


def test_command_rejects_address_as_receipt_alias() -> None:
    with pytest.raises(ValueError, match="safe non-address alias"):
        EcoCuteSetCommand("192.168.1.20", 0xC7, b"\x41", b"\x41")


def test_timeout_is_not_retried_or_verified() -> None:
    setter = FakeSetTransport(TimeoutError())
    reader = FakeReadTransport(0xC7, b"\x41")
    result = adapter(setter, reader).execute(
        EcoCuteSetCommand("main_water_heater", 0xC7, b"\x41", b"\x41")
    )
    assert len(setter.calls) == 1
    assert reader.calls == []
    assert result.dispatch.status is DispatchStatus.TIMEOUT
    assert result.verification.status is VerificationStatus.UNAVAILABLE
    assert result.verification.quality == "missing"
    assert result.outcome is OperationOutcome.UNKNOWN


def test_rejection_is_distinct_from_verification_failure() -> None:
    setter = FakeSetTransport(EchonetResponseError("device value omitted"))
    reader = FakeReadTransport(0xC7, b"\x41")
    result = adapter(setter, reader).execute(
        EcoCuteSetCommand("main_water_heater", 0xC7, b"\x41", b"\x41")
    )
    assert result.dispatch.status is DispatchStatus.REJECTED
    assert result.verification.status is VerificationStatus.NOT_SUPPORTED
    assert result.outcome is OperationOutcome.FAILED


def test_accepted_without_observed_get_capability_is_not_claimed_complete() -> None:
    setter = FakeSetTransport()
    reader = FakeReadTransport(0xC7, b"\x41")
    result = adapter(
        setter, reader, get_epcs=frozenset()
    ).execute(
        EcoCuteSetCommand("main_water_heater", 0xC7, b"\x41", b"\x41")
    )
    assert result.dispatch.status is DispatchStatus.ACCEPTED
    assert result.verification.status is VerificationStatus.NOT_SUPPORTED
    assert result.verification.quality == "unknown"
    assert result.outcome is OperationOutcome.UNKNOWN
    assert reader.calls == []


def test_mismatched_readback_is_reported_not_matched() -> None:
    setter = FakeSetTransport()
    reader = FakeReadTransport(0xC7, b"\x42")
    result = adapter(setter, reader).execute(
        EcoCuteSetCommand("main_water_heater", 0xC7, b"\x41", b"\x41")
    )
    assert result.verification.status is VerificationStatus.NOT_MATCHED
    assert result.outcome is OperationOutcome.FAILED


class FakeSocket:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.closed = False

    def settimeout(self, value: float) -> None:
        assert 0 < value <= 30

    def sendto(self, value: bytes, target: tuple[str, int]) -> None:
        self.sent.append((value, target))

    def recvfrom(self, maximum: int) -> tuple[bytes, tuple[str, int]]:
        assert maximum == 65_535
        return self.response, ("192.168.1.20", 3610)

    def close(self) -> None:
        self.closed = True


def test_set_transport_uses_private_unicast_and_one_setc_datagram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = bytes.fromhex("10810007026b0105ff017101c700")
    fake = FakeSocket(response)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("192.168.1.20", 3610))
        ],
    )
    transport = EcoCuteSetUdpTransport(
        "water-heater.local",
        socket_factory=lambda *args: fake,  # type: ignore[arg-type]
    )
    assert not hasattr(transport, "get")
    result = transport.set(
        transaction_id=7, epc=0xC7, data=b"\x41", instance_code=1
    )
    assert result.frame.service == 0x71
    assert len(fake.sent) == 1
    assert fake.sent[0][0][10] == 0x61
    assert fake.sent[0][1] == ("192.168.1.20", 3610)
    assert fake.closed


def test_set_transport_rejects_public_target_before_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("8.8.8.8", 3610))
        ],
    )
    transport = EcoCuteSetUdpTransport("example.invalid")
    with pytest.raises(EchonetTransportError, match="private network"):
        transport.set(transaction_id=7, epc=0xC7, data=b"\x41")
