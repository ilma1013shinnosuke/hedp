from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from hedp.adapters.miele import MieleReadOnlyCollector, MieleReader, SseEvent


FIXTURE = Path(__file__).parent / "fixtures/miele/washer_dryer_state_v1.json"
NOW = datetime.fromisoformat("2026-07-26T11:00:00+09:00")


class FakeTransport:
    def __init__(self, device: dict[str, object]) -> None:
        self.device = device

    def devices(self) -> object:
        return {
            "fixture-device-001": self.device,
            "other-private-device": {"state": {}},
        }

    def events(
        self,
        source_device_id: str,
        *,
        maximum_events: int,
        timeout_seconds: float,
    ):
        assert source_device_id == "fixture-device-001"
        assert maximum_events == 3
        assert timeout_seconds == 12
        yield SseEvent("PING", {"private": "heartbeat-secret"})
        state = {"state": self.device["state"]}
        yield SseEvent("ACTION", state)
        yield SseEvent("ACTION", state)


def _collector() -> MieleReadOnlyCollector:
    device = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return MieleReadOnlyCollector(
        MieleReader(FakeTransport(device)),
        source_device_id="fixture-device-001",
        target_ref="laundry-appliance",
        clock=lambda: NOW,
    )


def test_snapshot_keeps_only_allowlisted_state_and_fingerprint() -> None:
    raw = _collector().collect_snapshot()
    rendered = raw.to_json()

    assert raw.source == "miele_read_only"
    assert raw.payload["collection_kind"] == "snapshot"
    observation = raw.payload["observations"][0]
    assert observation["remaining_minutes"]["value"] == 195
    assert len(raw.payload["evidence_sha256"][0]) == 64
    for private in (
        "fixture-device-001",
        "other-private-device",
        "unknown_future_field",
    ):
        assert private not in rendered


def test_event_collection_is_bounded_and_deduplicates_equal_state() -> None:
    raw = _collector().collect_events(maximum_events=3, timeout_seconds=12)
    rendered = raw.to_json()

    assert raw.payload["input_count"] == 3
    assert raw.payload["discarded_count"] == 2
    assert len(raw.payload["observations"]) == 1
    assert raw.payload["observations"][0]["source"] == "sse"
    assert "heartbeat-secret" not in rendered
    assert "fixture-device-001" not in rendered


def test_event_limit_is_bounded() -> None:
    collector = _collector()

    for invalid in (0, 1_025):
        try:
            collector.collect_events(maximum_events=invalid)
        except ValueError as error:
            assert "between 1 and 1024" in str(error)
        else:
            raise AssertionError("invalid event limit was accepted")


def test_event_timeout_is_bounded() -> None:
    collector = _collector()

    for invalid in (0, 301):
        try:
            collector.collect_events(timeout_seconds=invalid)
        except ValueError as error:
            assert "greater than 0 and at most 300" in str(error)
        else:
            raise AssertionError("invalid timeout was accepted")
