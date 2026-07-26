from datetime import datetime, timezone
import struct

import pytest

from hedp.adapters.fusionsolar.modbus_tcp import ModbusTcpError
from hedp.adapters.fusionsolar.optimizer_file import (
    FusionSolarOptimizerCollector,
    HuaweiReadOnlyFileClient,
    HuaweiUploadedFile,
    parse_optimizer_realtime_file,
)


def _optimizer_file() -> bytes:
    record = struct.pack(
        ">HHHIHHHHhHI",
        17,
        1234,
        4567,
        0x00000010,
        4012,
        321,
        3890,
        287,
        -55,
        4,
        123456,
    )
    unit = struct.pack(">IIHH", 1_700_000_000, 0, 38, 1) + record
    return b"V101" + bytes(8) + unit


def test_optimizer_v101_parser_decodes_confirmed_fields():
    snapshots = parse_optimizer_realtime_file(_optimizer_file())

    assert len(snapshots) == 1
    assert snapshots[0].observed_epoch_local == 1_700_000_000
    assert snapshots[0].declared_length == 38
    optimizer = snapshots[0].optimizers[0]
    assert optimizer.address == 17
    assert optimizer.output_power_w == 123.4
    assert optimizer.voltage_to_ground_v == 456.7
    assert optimizer.alarm_bits == 0x10
    assert optimizer.output_voltage_v == 401.2
    assert optimizer.output_current_a == 3.21
    assert optimizer.input_voltage_v == 389.0
    assert optimizer.input_current_a == 2.87
    assert optimizer.temperature_c == -5.5
    assert optimizer.running_status_code == 4
    assert optimizer.accumulated_yield_kwh == 123.456


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"V102" + bytes(8),
        b"V101" + bytes(8) + b"\0",
        b"V101" + bytes(8) + struct.pack(">IIHH", 1, 0, 38, 1),
    ],
)
def test_optimizer_parser_rejects_unknown_or_truncated_files(payload):
    with pytest.raises(ValueError):
        parse_optimizer_realtime_file(payload)


class _PduClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def exchange_huawei_file_upload_pdu(self, request):
        self.requests.append(request)
        return self.responses.pop(0)


def test_file_client_uploads_frames_in_order_and_completes():
    payload = _optimizer_file()
    first, second = payload[:30], payload[30:]
    pdu = _PduClient(
        [
            bytes((0x41, 0x05, 6, 0x44))
            + struct.pack(">IB", len(payload), 30),
            bytes((0x41, 0x06, 3 + len(first), 0x44))
            + struct.pack(">H", 0)
            + first,
            bytes((0x41, 0x06, 3 + len(second), 0x44))
            + struct.pack(">H", 1)
            + second,
            bytes((0x41, 0x0C, 3, 0x44)) + struct.pack(">H", 0x1234),
        ]
    )

    result = HuaweiReadOnlyFileClient(pdu).upload_latest(0x44)

    assert result == HuaweiUploadedFile(0x44, payload, 0x1234)
    assert [request[1] for request in pdu.requests] == [0x05, 0x06, 0x06, 0x0C]


def test_file_client_retries_only_documented_busy_start_response():
    sleeps = []
    pdu = _PduClient(
        [
            b"\xC1\x06",
            bytes((0x41, 0x05, 6, 0x44)) + struct.pack(">IB", 0, 0),
            bytes((0x41, 0x0C, 3, 0x44)) + struct.pack(">H", 0),
        ]
    )

    HuaweiReadOnlyFileClient(pdu, sleep=sleeps.append).upload_latest(0x44)

    assert sleeps == [10]


def test_file_client_rejects_out_of_order_frame():
    pdu = _PduClient(
        [
            bytes((0x41, 0x05, 6, 0x44)) + struct.pack(">IB", 1, 1),
            bytes((0x41, 0x06, 4, 0x44)) + struct.pack(">H", 1) + b"x",
        ]
    )

    with pytest.raises(ModbusTcpError, match="frame number"):
        HuaweiReadOnlyFileClient(pdu).upload_latest(0x44)


def test_file_client_reports_only_safe_exception_classification():
    pdu = _PduClient([b"\xC1\x80"])

    with pytest.raises(ModbusTcpError, match="no_permission"):
        HuaweiReadOnlyFileClient(pdu).upload_latest(0x44)


def test_collector_preserves_protocol_evidence_without_serial_number(monkeypatch):
    class _FileClient:
        def upload_latest(self, file_type):
            assert file_type == 0x44
            return HuaweiUploadedFile(file_type, _optimizer_file(), 0x1234)

    monkeypatch.setattr(
        "hedp.adapters.fusionsolar.optimizer_file.datetime",
        type(
            "FixedDateTime",
            (),
            {
                "now": staticmethod(
                    lambda tz: datetime(2026, 7, 26, tzinfo=timezone.utc)
                )
            },
        ),
    )

    raw = FusionSolarOptimizerCollector(
        _FileClient(), target_alias="pv_primary"
    ).collect()

    item = raw.payload["snapshots"][0]["optimizers"][0]
    assert item["local_index"] == 1
    assert item["logical_address"] == 17
    assert raw.payload["file_payload_base64"]
    assert raw.metadata["identity_policy"] == "serial_number_not_collected"
