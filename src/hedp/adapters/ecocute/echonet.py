from __future__ import annotations

from dataclasses import dataclass


FORMAT_1 = bytes((0x10, 0x81))
GET_RESPONSE = 0x72
INFORMATION = 0x73
WATER_HEATER_CLASS = bytes((0x02, 0x6B))
PROPERTY_MAP_EPCS = frozenset((0x9D, 0x9E, 0x9F))

# Names are labels for values whose semantics were confirmed during the
# read-only observation.  Unlisted EPCs remain usable as numeric properties
# without acquiring a guessed name.
_CONFIRMED_PROPERTY_NAMES = {
    0x80: "operation_state",
    0x86: "manufacturer_fault_code",
    0x88: "fault_state",
    0x89: "fault_detail",
    0x9D: "inf_property_map",
    0x9E: "set_property_map",
    0x9F: "get_property_map",
    0xB2: "heating_active",
    0xC3: "hot_water_in_use",
    0xD1: "supply_temperature_setpoint_c",
    0xD3: "bath_temperature_setpoint_c",
    0xE1: "remaining_hot_water_l",
    0xEA: "bath_operation_state",
}


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


@dataclass(frozen=True)
class EchonetPropertyMap:
    """One decoded ECHONET Lite property map, represented as an EPC set."""

    epc: int
    properties: frozenset[int]


@dataclass(frozen=True)
class EchonetPropertyMaps:
    """The optional INF, Set, and Get maps found in one response frame."""

    inf: EchonetPropertyMap | None
    set: EchonetPropertyMap | None
    get: EchonetPropertyMap | None


@dataclass(frozen=True)
class ReadOnlyCapability:
    """An EPC advertised as Get-capable and not advertised as Set-capable."""

    epc: int
    name: str | None


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


def decode_property_map(prop: EchonetProperty) -> EchonetPropertyMap:
    """Decode the list or bitmap representation of a 9D, 9E, or 9F map."""
    if prop.epc not in PROPERTY_MAP_EPCS:
        raise FrameError(f"EPC {prop.epc:02X} is not a property map")
    if not prop.data:
        raise FrameError(f"EPC {prop.epc:02X} property map is empty")

    count = prop.data[0]
    if count < 16:
        if len(prop.data) != count + 1:
            raise FrameError(f"EPC {prop.epc:02X} list property map has invalid length")
        epcs = prop.data[1:]
    else:
        if len(prop.data) != 17:
            raise FrameError(f"EPC {prop.epc:02X} bitmap property map has invalid length")
        epcs = bytes(
            ((high_nibble + 8) << 4) | low_nibble
            for low_nibble, bitmap in enumerate(prop.data[1:])
            for high_nibble in range(8)
            if bitmap & (1 << high_nibble)
        )
        if len(epcs) != count:
            raise FrameError(f"EPC {prop.epc:02X} bitmap property map has invalid count")

    if len(set(epcs)) != len(epcs):
        raise FrameError(f"EPC {prop.epc:02X} property map contains duplicate EPCs")
    return EchonetPropertyMap(prop.epc, frozenset(epcs))


def decode_property_maps(frame: EchonetFrame) -> EchonetPropertyMaps:
    """Extract property maps from a parsed frame without discarding other EPCs."""
    maps: dict[int, EchonetPropertyMap] = {}
    for prop in frame.properties:
        if prop.epc not in PROPERTY_MAP_EPCS:
            continue
        if prop.epc in maps:
            raise FrameError(f"duplicate EPC {prop.epc:02X} property map")
        maps[prop.epc] = decode_property_map(prop)
    return EchonetPropertyMaps(maps.get(0x9D), maps.get(0x9E), maps.get(0x9F))


def classify_read_only_capabilities(
    property_maps: EchonetPropertyMaps,
) -> tuple[ReadOnlyCapability, ...]:
    """Classify only EPCs confirmed read-only by both observed access maps.

    This intentionally does not infer writable capabilities.  An EPC absent
    from the Set map is classified only when it is also present in the Get map.
    Unknown EPCs are retained with ``name=None``.
    """
    if property_maps.get is None or property_maps.set is None:
        raise FrameError("Get and Set property maps are required")
    return tuple(
        ReadOnlyCapability(epc, _CONFIRMED_PROPERTY_NAMES.get(epc))
        for epc in sorted(property_maps.get.properties - property_maps.set.properties)
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
