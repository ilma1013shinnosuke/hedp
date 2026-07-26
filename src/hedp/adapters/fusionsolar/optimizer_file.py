from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import struct
import time
from typing import Callable

from hedp.adapters.fusionsolar.modbus_tcp import (
    ModbusTcpError,
    ReadOnlyModbusTcpClient,
)
from hedp.storage import RawData


OPTIMIZER_REALTIME_FILE_TYPE = 0x44
_FILE_VERSION = b"V101"
_OPTIMIZER_RECORD_SIZE = 26
_MAX_FILE_SIZE = 16 * 1024 * 1024
_EXCEPTION_NAMES = {
    0x01: "illegal_function",
    0x02: "illegal_data_address",
    0x03: "illegal_data_value",
    0x04: "device_failure",
    0x06: "device_busy",
    0x80: "no_permission",
}


@dataclass(frozen=True)
class HuaweiUploadedFile:
    file_type: int
    payload: bytes
    device_crc: int


@dataclass(frozen=True)
class OptimizerRealtime:
    address: int
    output_power_w: float
    voltage_to_ground_v: float
    alarm_bits: int
    output_voltage_v: float
    output_current_a: float
    input_voltage_v: float
    input_current_a: float
    temperature_c: float
    running_status_code: int
    accumulated_yield_kwh: float


@dataclass(frozen=True)
class OptimizerRealtimeSnapshot:
    observed_epoch_local: int
    declared_length: int
    optimizers: tuple[OptimizerRealtime, ...]


class HuaweiReadOnlyFileClient:
    """Read files uploaded by a Huawei device through function 0x41.

    The terminology follows Huawei's specification: the device uploads bytes
    to this client.  This class exposes no register-write or configuration
    operation.
    """

    def __init__(
        self,
        client: ReadOnlyModbusTcpClient,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self._sleep = sleep

    def upload_latest(self, file_type: int) -> HuaweiUploadedFile:
        if not 0 <= file_type <= 255:
            raise ValueError("file_type must be between 0 and 255")

        start = self._start_upload(file_type)
        file_length, frame_length = _parse_start_response(start, file_type)
        if file_length > _MAX_FILE_SIZE:
            raise ModbusTcpError("Huawei uploaded file exceeds the safety limit")
        if file_length and not frame_length:
            raise ModbusTcpError("Huawei uploaded file has an invalid frame length")

        payload = bytearray()
        frame_number = 0
        while len(payload) < file_length:
            response = self.client.exchange_huawei_file_upload_pdu(
                struct.pack(">BBBBH", 0x41, 0x06, 3, file_type, frame_number)
            )
            response_frame, frame_data = _parse_data_response(
                response, file_type, frame_number
            )
            if response_frame != frame_number:
                raise ModbusTcpError("Huawei uploaded file frame is out of order")
            if not frame_data or len(frame_data) > frame_length:
                raise ModbusTcpError("Huawei uploaded file frame length is invalid")
            payload.extend(frame_data)
            if len(payload) > file_length:
                raise ModbusTcpError("Huawei uploaded file is longer than declared")
            frame_number += 1
            if frame_number > 65535:
                raise ModbusTcpError("Huawei uploaded file has too many frames")

        completion = self.client.exchange_huawei_file_upload_pdu(
            bytes((0x41, 0x0C, 1, file_type))
        )
        device_crc = _parse_completion_response(completion, file_type)
        return HuaweiUploadedFile(file_type, bytes(payload), device_crc)

    def _start_upload(self, file_type: int) -> bytes:
        request = bytes((0x41, 0x05, 1, file_type))
        for attempt in range(7):
            response = self.client.exchange_huawei_file_upload_pdu(request)
            if response[:2] != b"\xC1\x06":
                return response
            if attempt == 6:
                break
            self._sleep(10)
        raise ModbusTcpError("Huawei device remained busy during file upload")


class FusionSolarOptimizerCollector:
    """Collect the latest five-minute optimizer snapshot without identifiers."""

    source = "fusionsolar_optimizer_realtime"

    def __init__(
        self,
        file_client: HuaweiReadOnlyFileClient,
        *,
        target_alias: str,
    ) -> None:
        if not target_alias:
            raise ValueError("target_alias must not be empty")
        self.file_client = file_client
        self.target_alias = target_alias

    def collect(self) -> RawData:
        uploaded = self.file_client.upload_latest(OPTIMIZER_REALTIME_FILE_TYPE)
        snapshots = parse_optimizer_realtime_file(uploaded.payload)
        return RawData(
            source=self.source,
            timestamp=datetime.now(timezone.utc),
            payload={
                "file_version": "V101",
                "file_payload_base64": base64.b64encode(uploaded.payload).decode(
                    "ascii"
                ),
                "snapshots": [
                    {
                        "observed_epoch_local": snapshot.observed_epoch_local,
                        "declared_length": snapshot.declared_length,
                        "optimizers": [
                            {
                                "local_index": index,
                                "logical_address": item.address,
                                "output_power_w": item.output_power_w,
                                "voltage_to_ground_v": item.voltage_to_ground_v,
                                "alarm_bits": item.alarm_bits,
                                "output_voltage_v": item.output_voltage_v,
                                "output_current_a": item.output_current_a,
                                "input_voltage_v": item.input_voltage_v,
                                "input_current_a": item.input_current_a,
                                "temperature_c": item.temperature_c,
                                "running_status_code": item.running_status_code,
                                "accumulated_yield_kwh": (
                                    item.accumulated_yield_kwh
                                ),
                            }
                            for index, item in enumerate(
                                snapshot.optimizers, start=1
                            )
                        ],
                    }
                    for snapshot in snapshots
                ],
            },
            metadata={
                "target_alias": self.target_alias,
                "file_type": OPTIMIZER_REALTIME_FILE_TYPE,
                "device_crc": uploaded.device_crc,
                "identity_policy": "serial_number_not_collected",
            },
        )


def parse_optimizer_realtime_file(
    payload: bytes,
) -> tuple[OptimizerRealtimeSnapshot, ...]:
    if len(payload) < 12 or payload[:4] != _FILE_VERSION:
        raise ValueError("unsupported Huawei optimizer file version")

    snapshots: list[OptimizerRealtimeSnapshot] = []
    offset = 12
    while offset < len(payload):
        if len(payload) - offset < 12:
            raise ValueError("truncated Huawei optimizer snapshot header")
        observed, _reserved, declared_length, count = struct.unpack_from(
            ">IIHH", payload, offset
        )
        size = 12 + count * _OPTIMIZER_RECORD_SIZE
        if len(payload) - offset < size:
            raise ValueError("truncated Huawei optimizer snapshot")
        records = tuple(
            _parse_optimizer(payload, offset + 12 + index * _OPTIMIZER_RECORD_SIZE)
            for index in range(count)
        )
        snapshots.append(
            OptimizerRealtimeSnapshot(observed, declared_length, records)
        )
        offset += size
    return tuple(snapshots)


def _parse_optimizer(payload: bytes, offset: int) -> OptimizerRealtime:
    (
        address,
        output_power,
        voltage_to_ground,
        alarm,
        output_voltage,
        output_current,
        input_voltage,
        input_current,
        temperature,
        running_status,
        accumulated_yield,
    ) = struct.unpack_from(">HHHIHHHHhHI", payload, offset)
    return OptimizerRealtime(
        address=address,
        output_power_w=output_power / 10,
        voltage_to_ground_v=voltage_to_ground / 10,
        alarm_bits=alarm,
        output_voltage_v=output_voltage / 10,
        output_current_a=output_current / 100,
        input_voltage_v=input_voltage / 10,
        input_current_a=input_current / 100,
        temperature_c=temperature / 10,
        running_status_code=running_status,
        accumulated_yield_kwh=accumulated_yield / 1000,
    )


def _parse_start_response(response: bytes, expected_file_type: int) -> tuple[int, int]:
    _validate_response(response, 0x05, expected_file_type, minimum_data_length=6)
    return struct.unpack_from(">IB", response, 4)


def _parse_data_response(
    response: bytes, expected_file_type: int, expected_frame: int
) -> tuple[int, bytes]:
    _validate_response(response, 0x06, expected_file_type, minimum_data_length=3)
    frame_number = struct.unpack_from(">H", response, 4)[0]
    if frame_number != expected_frame:
        raise ModbusTcpError("Huawei uploaded file frame number does not match")
    return frame_number, response[6:]


def _parse_completion_response(response: bytes, expected_file_type: int) -> int:
    _validate_response(response, 0x0C, expected_file_type, minimum_data_length=3)
    if len(response) != 6:
        raise ModbusTcpError("Huawei file completion response length is invalid")
    return struct.unpack_from(">H", response, 4)[0]


def _validate_response(
    response: bytes,
    subfunction: int,
    expected_file_type: int,
    *,
    minimum_data_length: int,
) -> None:
    if len(response) == 2 and response[0] == 0xC1:
        name = _EXCEPTION_NAMES.get(response[1], "unknown")
        raise ModbusTcpError(f"Huawei file upload rejected: {name}")
    if len(response) < 4:
        raise ModbusTcpError("Huawei file-upload response is truncated")
    if response[0] != 0x41 or response[1] != subfunction:
        raise ModbusTcpError("unexpected Huawei file-upload response")
    data_length = response[2]
    if data_length < minimum_data_length or len(response) != data_length + 3:
        raise ModbusTcpError("Huawei file-upload data length does not match")
    if response[3] != expected_file_type:
        raise ModbusTcpError("Huawei uploaded file type does not match")
