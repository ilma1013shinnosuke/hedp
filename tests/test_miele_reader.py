from __future__ import annotations

import json
from pathlib import Path

import pytest

from hedp.adapters.miele import (
    CollectionSource,
    MieleReader,
    SseEvent,
    normalize_observation,
    parse_sse,
    state_from_event,
)
from hedp.observations import ObservationTime, Quality


FIXTURES = Path(__file__).parent / "fixtures" / "miele"
TIME = ObservationTime(
    "2026-07-25T10:00:00+09:00",
    "2026-07-25T10:00:01+09:00",
)


def _state() -> dict[str, object]:
    return json.loads(
        (FIXTURES / "washer_dryer_state_v1.json").read_text(encoding="utf-8")
    )


def test_normalizes_rest_snapshot_with_common_quality_and_time() -> None:
    observation = normalize_observation(
        _state(),
        target_ref="laundry-appliance",
        source=CollectionSource.REST,
        time=TIME,
    )

    assert observation.quality == Quality.GOOD
    assert observation.remaining_minutes.value == 195
    assert observation.temperature_c.value == 40
    assert observation.time == TIME
    assert "laundry-appliance" not in repr(observation)


def test_missing_and_invalid_values_are_not_filled() -> None:
    observation = normalize_observation(
        {
            "state": {
                "status": {"value_raw": -32_768},
                "temperature": True,
            }
        },
        target_ref="laundry-appliance",
        source=CollectionSource.REST,
        time=TIME,
    )

    assert observation.quality == Quality.INVALID
    assert observation.status_code.value is None
    assert observation.status_code.quality == Quality.MISSING
    assert observation.temperature_c.value is None
    assert observation.temperature_c.quality == Quality.INVALID


def test_parses_bounded_sse_transcript_and_ignores_ping_state() -> None:
    events = list(
        parse_sse(
            (FIXTURES / "sse_transcript_v1.txt")
            .read_text(encoding="utf-8")
            .splitlines()
        )
    )

    assert [event.name for event in events] == ["PING", "IDENT"]
    assert state_from_event(events[0]) is None
    state = state_from_event(events[1])
    assert state is not None
    observation = normalize_observation(
        state,
        target_ref="laundry-appliance",
        source=CollectionSource.SSE,
        time=TIME,
    )
    assert observation.status_code.value == 5
    assert observation.remaining_minutes.value == 30


def test_sse_payload_is_hidden_from_repr_and_size_is_bounded() -> None:
    private = "private-account-or-appliance-value"
    event = next(parse_sse([f'data: {{"state":{{"private":"{private}"}}}}', ""]))

    assert private not in repr(event)
    large = "x" * 50
    with pytest.raises(ValueError, match="byte limit"):
        list(parse_sse([f'data: {{"value":"{large}"}}', ""], max_event_bytes=10))


def test_type_24_nested_event_is_selected_without_retaining_device_id() -> None:
    private_id = "private-device-id"
    event = SseEvent(
        "ACTION",
        {
            private_id: {
                "ident": {"type": {"value_raw": 24}},
                "state": {"status": {"value_raw": 4}},
            }
        },
    )

    state = state_from_event(event)

    assert state == {"state": {"status": {"value_raw": 4}}}
    assert private_id not in repr(state)
    assert private_id not in repr(event)


def test_reader_interface_has_no_appliance_action() -> None:
    class FakeTransport:
        def devices(self) -> object:
            return {}

        def events(
            self,
            source_device_id: str,
            *,
            maximum_events: int,
            timeout_seconds: float,
        ):
            assert maximum_events == 1
            assert timeout_seconds == 2
            yield SseEvent("PING", {})

    reader = MieleReader(FakeTransport())

    assert reader.devices() == {}
    assert next(
        reader.events("fixture", maximum_events=1, timeout_seconds=2)
    ).name == "PING"
    assert not hasattr(reader, "start")
    assert not hasattr(reader, "stop")


def test_reader_requires_finite_sse_bounds() -> None:
    class FakeTransport:
        def devices(self) -> object:
            return {}

        def events(
            self,
            source_device_id: str,
            *,
            maximum_events: int,
            timeout_seconds: float,
        ):
            yield SseEvent("PING", {})

    reader = MieleReader(FakeTransport())

    for kwargs in (
        {"maximum_events": 0, "timeout_seconds": 1},
        {"maximum_events": 1, "timeout_seconds": 0},
        {"maximum_events": 1, "timeout_seconds": 301},
    ):
        with pytest.raises(ValueError):
            reader.events("fixture", **kwargs)


def test_sse_rejects_non_object_and_excessive_lines() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        list(parse_sse(["data: []", ""]))
    with pytest.raises(ValueError, match="data-line limit"):
        list(parse_sse(["data: {", "data: }", ""], max_data_lines=1))
