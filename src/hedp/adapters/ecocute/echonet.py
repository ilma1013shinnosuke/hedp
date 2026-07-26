from __future__ import annotations

from dataclasses import dataclass


FORMAT_1 = bytes((0x10, 0x81))
GET_REQUEST = 0x62
GET_RESPONSE = 0x72
INFORMATION = 0x73
SET_REQUEST = 0x61
SET_RESPONSE = 0x71
WATER_HEATER_CLASS = bytes((0x02, 0x6B))
CONTROLLER_OBJECT = bytes((0x05, 0xFF, 0x01))
PROPERTY_MAP_EPCS = frozenset((0x9D, 0x9E, 0x9F))
MAX_GET_PROPERTIES = 4

# Names are labels for values whose semantics were confirmed during the
# read-only observation.  Unlisted EPCs remain usable as numeric properties
# without acquiring a guessed name.
_CONFIRMED_PROPERTY_NAMES = {
    0x80: "operation_state",
    0x86: "manufacturer_fault_code",
    0x88: "fault_state",
    0x89: "fault_detail",
    0x93: "remote_operation_setting",
    0x9D: "inf_property_map",
    0x9E: "set_property_map",
    0x9F: "get_property_map",
    0xB0: "heating_mode",
    0xB2: "heating_active",
    0xC0: "daytime_boost_allowed",
    0xC3: "hot_water_in_use",
    0xC7: "energy_shift_participation",
    0xC8: "heating_start_base_time",
    0xC9: "energy_shift_count",
    0xCA: "daytime_heating_shift_time_1",
    0xCB: "predicted_heating_energy_1",
    0xCC: "hourly_energy_profile_1",
    0xD1: "supply_temperature_setpoint_c",
    0xD3: "bath_temperature_setpoint_c",
    0xE1: "remaining_hot_water_l",
    0xE3: "bath_auto_enabled",
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
        return self.source_object[:2] == WATER_HEATER_CLASS and self.service in {
            GET_RESPONSE,
            INFORMATION,
        }


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


def confirmed_property_name(epc: int) -> str | None:
    """Return only names supported by observed/specification evidence."""

    return _CONFIRMED_PROPERTY_NAMES.get(epc)


def build_get_request(
    *,
    transaction_id: int,
    epcs: tuple[int, ...],
    instance_code: int = 1,
) -> bytes:
    """Build one side-effect-free ECHONET Lite Get request.

    Network discovery, destination addresses, retries, and scheduling stay
    outside this pure function so the same Adapter can run on macOS or Linux.
    """

    if isinstance(transaction_id, bool) or not isinstance(transaction_id, int):
        raise TypeError("transaction_id must be an integer")
    if not 0 <= transaction_id <= 0xFFFF:
        raise ValueError("transaction_id must be between 0 and 65535")
    if isinstance(instance_code, bool) or not isinstance(instance_code, int):
        raise TypeError("instance_code must be an integer")
    if not 1 <= instance_code <= 0xFF:
        raise ValueError("instance_code must be between 1 and 255")
    if not epcs:
        raise ValueError("epcs must not be empty")
    if len(epcs) > MAX_GET_PROPERTIES:
        raise ValueError("at most four EPCs may be requested")
    if len(set(epcs)) != len(epcs):
        raise ValueError("epcs must not contain duplicates")
    for epc in epcs:
        if isinstance(epc, bool) or not isinstance(epc, int):
            raise TypeError("each EPC must be an integer")
        if not 0 <= epc <= 0xFF:
            raise ValueError("each EPC must be between 0 and 255")

    destination = WATER_HEATER_CLASS + bytes((instance_code,))
    properties = b"".join(bytes((epc, 0)) for epc in epcs)
    return (
        FORMAT_1
        + transaction_id.to_bytes(2, "big")
        + CONTROLLER_OBJECT
        + destination
        + bytes((GET_REQUEST, len(epcs)))
        + properties
    )


def build_set_request(
    *,
    transaction_id: int,
    epc: int,
    data: bytes,
    instance_code: int = 1,
) -> bytes:
    """Build one ECHONET Lite SetC request without assigning EPC semantics.

    Callers must separately prove that the target advertised ``epc`` in its
    runtime-observed Set property map.  Keeping that gate outside this byte
    builder prevents a specification-only capability from becoming executable.
    """

    if isinstance(transaction_id, bool) or not isinstance(transaction_id, int):
        raise TypeError("transaction_id must be an integer")
    if not 0 <= transaction_id <= 0xFFFF:
        raise ValueError("transaction_id must be between 0 and 65535")
    if isinstance(instance_code, bool) or not isinstance(instance_code, int):
        raise TypeError("instance_code must be an integer")
    if not 1 <= instance_code <= 0xFF:
        raise ValueError("instance_code must be between 1 and 255")
    if isinstance(epc, bool) or not isinstance(epc, int):
        raise TypeError("epc must be an integer")
    if not 0 <= epc <= 0xFF:
        raise ValueError("epc must be between 0 and 255")
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    if not data:
        raise ValueError("data must not be empty")
    if len(data) > 0xFF:
        raise ValueError("data must contain at most 255 bytes")

    destination = WATER_HEATER_CLASS + bytes((instance_code,))
    return (
        FORMAT_1
        + transaction_id.to_bytes(2, "big")
        + CONTROLLER_OBJECT
        + destination
        + bytes((SET_REQUEST, 1, epc, len(data)))
        + data
    )


def build_setc_request(
    *,
    transaction_id: int,
    properties: tuple[EchonetProperty, ...],
    instance_code: int = 1,
) -> bytes:
    """Build one finite, multi-property ECHONET Lite SetC request.

    EcoCute operations that were recovered from the verified controller use a
    remote-operation marker followed by one operation property in the *same*
    SetC frame.  This builder preserves that ordering while assigning no
    semantics to either property.
    """

    if not properties:
        raise ValueError("properties must not be empty")
    if len(properties) > 0xFF:
        raise ValueError("at most 255 properties may be set")
    if len({prop.epc for prop in properties}) != len(properties):
        raise ValueError("properties must not contain duplicate EPCs")
    for prop in properties:
        if not isinstance(prop, EchonetProperty):
            raise TypeError("each property must be an EchonetProperty")
        if isinstance(prop.epc, bool) or not isinstance(prop.epc, int):
            raise TypeError("each EPC must be an integer")
        if not 0 <= prop.epc <= 0xFF:
            raise ValueError("each EPC must be between 0 and 255")
        if not isinstance(prop.data, bytes) or not prop.data:
            raise ValueError("each property data must be non-empty bytes")
        if len(prop.data) > 0xFF:
            raise ValueError("each property data must contain at most 255 bytes")

    # Reuse the single-property builder for shared transaction and instance
    # validation, then replace its OPC/property tail deterministically.
    prefix = build_set_request(
        transaction_id=transaction_id,
        epc=properties[0].epc,
        data=properties[0].data,
        instance_code=instance_code,
    )[:11]
    encoded = b"".join(
        bytes((prop.epc, len(prop.data))) + prop.data for prop in properties
    )
    return prefix + bytes((len(properties),)) + encoded


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
            raise FrameError(
                f"EPC {prop.epc:02X} bitmap property map has invalid length"
            )
        epcs = bytes(
            ((high_nibble + 8) << 4) | low_nibble
            for low_nibble, bitmap in enumerate(prop.data[1:])
            for high_nibble in range(8)
            if bitmap & (1 << high_nibble)
        )
        if len(epcs) != count:
            raise FrameError(
                f"EPC {prop.epc:02X} bitmap property map has invalid count"
            )

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
    if prop.epc in {0x80, 0x93, 0xB2, 0xC0, 0xC3, 0xE3}:
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
    if prop.epc == 0xC7:
        if len(prop.data) != 1:
            raise FrameError("EPC C7 must contain one byte")
        return {
            0x00: "not_participating",
            0x01: "participating",
        }.get(prop.data[0], "unknown")
    if prop.epc == 0xC8:
        if len(prop.data) != 1:
            raise FrameError("EPC C8 must contain one byte")
        return {
            0x00: "20:00",
            0x01: "21:00",
            0x02: "22:00",
            0x03: "23:00",
            0x04: "00:00",
            0x05: "01:00",
        }.get(prop.data[0], "unknown")
    if prop.epc == 0xC9:
        if len(prop.data) != 1:
            raise FrameError("EPC C9 must contain one byte")
        return prop.data[0] if prop.data[0] <= 2 else "unknown"
    if prop.epc == 0xCA:
        if len(prop.data) != 1:
            raise FrameError("EPC CA must contain one byte")
        return (
            f"{9 + prop.data[0]:02d}:00" if 0x00 <= prop.data[0] <= 0x08 else "unknown"
        )
    if prop.epc in {0xD1, 0xD3}:
        if len(prop.data) != 1:
            raise FrameError(f"EPC {prop.epc:02X} must contain one byte")
        return prop.data[0]
    if prop.epc == 0xE1:
        if len(prop.data) != 2:
            raise FrameError("EPC E1 must contain two bytes")
        return int.from_bytes(prop.data, "big")
    return None
