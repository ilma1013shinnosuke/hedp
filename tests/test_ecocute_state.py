from __future__ import annotations

import pytest

from hedp.adapters.ecocute import (
    EchonetFrame,
    EchonetProperty,
    FrameError,
    ObservationSource,
    build_get_request,
    normalize_observation,
    parse_frame,
)
from hedp.observations import ObservationTime, Quality


TIME = ObservationTime(
    "2026-07-25T10:00:00+09:00",
    "2026-07-25T10:00:01+09:00",
)


def test_builds_exact_read_only_get_request_without_network_configuration() -> None:
    request = build_get_request(
        transaction_id=1,
        epcs=(0x80, 0xB2, 0xC3, 0xE1),
    )

    assert request.hex() == "1081000105ff01026b0162048000b200c300e100"
    assert parse_frame(request).service == 0x62


def test_normalizes_periodic_get_without_fabricating_absent_properties() -> None:
    frame = parse_frame(
        bytes.fromhex("10810001026b0105ff017202800130e102012c")
    )
    observation = normalize_observation(frame, time=TIME)

    assert observation.source == ObservationSource.PERIODIC
    assert observation.quality == Quality.GOOD
    values = {prop.name: prop.reading.value for prop in observation.properties}
    assert values == {
        "operation_state": True,
        "remaining_hot_water_l": 300,
    }
    assert len(observation.properties) == 2


def test_normalizes_inf_as_second_precision_event_update() -> None:
    frame = parse_frame(bytes.fromhex("10810002026b0105ff017301c30141"))
    observation = normalize_observation(frame, time=TIME)

    assert observation.source == ObservationSource.EVENT
    assert observation.properties[0].name == "hot_water_in_use"
    assert observation.properties[0].reading.value is True


def test_unknown_and_missing_values_remain_explicit() -> None:
    frame = EchonetFrame(
        1,
        bytes((0x02, 0x6B, 0x01)),
        bytes((0x05, 0xFF, 0x01)),
        0x72,
        (
            EchonetProperty(0xF0, b"\x00"),
            EchonetProperty(0xE1, b""),
        ),
    )
    observation = normalize_observation(frame, time=TIME)

    assert observation.quality == Quality.UNKNOWN
    assert observation.properties[0].reading.quality == Quality.UNKNOWN
    assert observation.properties[0].reading.value is None
    assert observation.properties[1].reading.quality == Quality.MISSING


def test_rejects_wrong_device_service_and_duplicate_properties() -> None:
    wrong = EchonetFrame(
        1,
        bytes((0x01, 0x30, 0x01)),
        bytes((0x05, 0xFF, 0x01)),
        0x72,
        (),
    )
    duplicate = EchonetFrame(
        1,
        bytes((0x02, 0x6B, 0x01)),
        bytes((0x05, 0xFF, 0x01)),
        0x73,
        (EchonetProperty(0x80, b"\x30"), EchonetProperty(0x80, b"\x31")),
    )

    with pytest.raises(FrameError, match="not a water-heater"):
        normalize_observation(wrong, time=TIME)
    with pytest.raises(FrameError, match="duplicate"):
        normalize_observation(duplicate, time=TIME)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"transaction_id": -1, "epcs": (0x80,)},
        {"transaction_id": 1, "epcs": ()},
        {"transaction_id": 1, "epcs": (0x80, 0x80)},
        {"transaction_id": 1, "epcs": (0x100,)},
    ],
)
def test_invalid_get_requests_are_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        build_get_request(**kwargs)  # type: ignore[arg-type]
