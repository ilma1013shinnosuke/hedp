from __future__ import annotations

from dataclasses import dataclass


FORMAT_1 = bytes((0x10, 0x81))
GET_RESPONSE = 0x72
INFORMATION = 0x73
WATER_HEATER_CLASS = bytes((0x02, 0x6B))


class FrameError(ValueError):
    """ECHONET Lite frameの構造が不正。"""


@dataclass(frozen=True)
class EchonetProperty:
    epc: int
    data: bytes


@dataclass(frozen=True)
class EchonetFrame:
    transaction_id: int
    source_object: bytes
    destination_object: bytes
    service: int
    properties: tuple[EchonetProperty, ...]

    @property
    def is_water_heater_response(self) -> bool:
        return (
            self.source_object[:2] == WATER_HEATER_CLASS
            and self.service in {GET_RESPONSE, INFORMATION}
        )


def parse_frame(raw: bytes) -> EchonetFrame:
    if not isinstance(raw, bytes):
        raise TypeError("raw must be bytes")
    if len(raw) < 12:
        raise FrameError("frame is too short")
    if raw[:2] != FORMAT_1:
        raise FrameError("unsupported ECHONET header")

    transaction_id = int.from_bytes(raw[2:4], "big")
    source_object = raw[4:7]
    destination_object = raw[7:10]
    service = raw[10]
    property_count = raw[11]
    offset = 12
    properties: list[EchonetProperty] = []
    for _ in range(property_count):
        if offset + 2 > len(raw):
            raise FrameError("property header is truncated")
        epc, length = raw[offset], raw[offset + 1]
        offset += 2
        if offset + length > len(raw):
            raise FrameError("property data is truncated")
        properties.append(EchonetProperty(epc, raw[offset : offset + length]))
        offset += length
    if offset != len(raw):
        raise FrameError("unexpected trailing bytes")
    return EchonetFrame(
        transaction_id,
        source_object,
        destination_object,
        service,
        tuple(properties),
    )


def decode_known_property(prop: EchonetProperty) -> object:
    if prop.epc in {0x80, 0xB2, 0xC0, 0xC3, 0xE3}:
        if len(prop.data) != 1:
            raise FrameError(f"EPC {prop.epc:02X} must contain one byte")
        return {0x30: True, 0x31: False, 0x41: True, 0x42: False}.get(
            prop.data[0], "unknown"
        )
    if prop.epc == 0x88:
        if len(prop.data) != 1:
            raise FrameError("EPC 88 must contain one byte")
        return {0x41: "fault", 0x42: "no_fault"}.get(prop.data[0], "unknown")
    if prop.epc == 0xB0:
        if len(prop.data) != 1:
            raise FrameError("EPC B0 must contain one byte")
        return {
            0x41: "automatic",
            0x42: "manual_boost",
            0x43: "manual_stop",
        }.get(prop.data[0], "unknown")
    if prop.epc in {0xD1, 0xD3}:
        if len(prop.data) != 1:
            raise FrameError(f"EPC {prop.epc:02X} must contain one byte")
        return prop.data[0]
    if prop.epc == 0xE1:
        if len(prop.data) != 2:
            raise FrameError("EPC E1 must contain two bytes")
        return int.from_bytes(prop.data, "big")
    return None
