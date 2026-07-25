import json
from pathlib import Path

import pytest

from hedp.adapters.ecocute.echonet import (
    EchonetProperty,
    EchonetPropertyMaps,
    FrameError,
    classify_read_only_capabilities,
    decode_known_property,
    decode_property_map,
    decode_property_maps,
    parse_frame,
)


FIXTURE = Path(__file__).parent / "fixtures/ecocute/get_response_v1.json"
PROPERTY_MAP_FIXTURE = Path(__file__).parent / "fixtures/ecocute/property_maps_v1.json"


def test_parses_anonymous_water_heater_response() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    frame = parse_frame(bytes.fromhex(fixture["packet_hex"]))

    assert frame.is_water_heater_response
    assert frame.transaction_id == 1
    assert [prop.epc for prop in frame.properties] == [0x80, 0xB0, 0xE1]
    assert [decode_known_property(prop) for prop in frame.properties] == [
        True,
        "manual_boost",
        300,
    ]


def test_unknown_property_is_preserved_but_not_guessed() -> None:
    frame = parse_frame(bytes.fromhex("10810001026b0105ff017301f00100"))

    assert frame.properties[0].epc == 0xF0
    assert frame.properties[0].data == b"\x00"
    assert decode_known_property(frame.properties[0]) is None


def test_decodes_list_and_bitmap_property_maps_from_anonymous_fixture() -> None:
    fixture = json.loads(PROPERTY_MAP_FIXTURE.read_text(encoding="utf-8"))

    inf_map = decode_property_map(
        EchonetProperty(
            0x9D, bytes.fromhex(fixture["synthetic_inf_property_map_edt_hex"])
        )
    )
    get_map = decode_property_map(
        EchonetProperty(
            0x9F,
            bytes.fromhex(fixture["confirmed_he_wu46kq_get_property_map_edt_hex"]),
        )
    )

    assert inf_map.properties == frozenset((0x80, 0xB2, 0xC3))
    assert len(get_map.properties) == 41
    assert {0x80, 0xB0, 0xB2, 0xC3, 0xD1, 0xE1, 0xF0} <= get_map.properties


def test_extracts_maps_and_classifies_only_confirmed_read_only_epcs() -> None:
    fixture = json.loads(PROPERTY_MAP_FIXTURE.read_text(encoding="utf-8"))
    maps = decode_property_maps(parse_frame(bytes.fromhex(fixture["packet_hex"])))

    assert maps.inf is not None
    assert maps.set is not None
    assert maps.get is not None
    assert maps.set.properties == frozenset(
        (0x81, 0x93, 0xB0, 0xB4, 0xC0, 0xC7, 0xCA, 0xE3, *range(0xF3, 0xF9))
    )

    capabilities = {item.epc: item.name for item in classify_read_only_capabilities(maps)}

    assert capabilities[0xB2] == "heating_active"
    assert capabilities[0xC3] == "hot_water_in_use"
    assert capabilities[0xE1] == "remaining_hot_water_l"
    assert capabilities[0xF0] is None
    assert 0xB0 not in capabilities
    assert 0xC0 not in capabilities
    assert 0xE3 not in capabilities


@pytest.mark.parametrize(
    ("prop", "message"),
    [
        (EchonetProperty(0x9D, b""), "empty"),
        (EchonetProperty(0x9D, bytes.fromhex("0280")), "invalid length"),
        (EchonetProperty(0x9E, bytes.fromhex("028080")), "duplicate"),
        (EchonetProperty(0x9F, bytes.fromhex("1000000000000000000000000000000000")), "invalid count"),
    ],
)
def test_invalid_property_maps_are_rejected(
    prop: EchonetProperty, message: str
) -> None:
    with pytest.raises(FrameError, match=message):
        decode_property_map(prop)


def test_read_only_classification_requires_both_access_maps() -> None:
    get_map = decode_property_map(EchonetProperty(0x9F, bytes.fromhex("0180")))

    with pytest.raises(FrameError, match="Get and Set"):
        classify_read_only_capabilities(EchonetPropertyMaps(None, None, get_map))


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        bytes.fromhex("10820001026b0105ff017200"),
        bytes.fromhex("10810001026b0105ff0172018002ff"),
        bytes.fromhex("10810001026b0105ff017200ff"),
    ],
)
def test_invalid_frames_are_rejected(raw: bytes) -> None:
    with pytest.raises(FrameError):
        parse_frame(raw)
