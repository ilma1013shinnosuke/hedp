import json
from pathlib import Path

import pytest

from hedp.adapters.ecocute.echonet import FrameError, decode_known_property, parse_frame


FIXTURE = Path(__file__).parent / "fixtures/ecocute/get_response_v1.json"


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
