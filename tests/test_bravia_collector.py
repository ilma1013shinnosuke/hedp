from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from hedp.adapters.bravia import BraviaReadOnlyCollector


FIXTURE = (
    Path(__file__).parent / "fixtures" / "bravia" / "active_anonymous.json"
)
NOW = datetime.fromisoformat("2026-07-27T08:00:00+09:00")


class FakeReadTransport:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, float]] = []

    def power_status(self, *, timeout_seconds: float):
        self.calls.append(("power", timeout_seconds))
        return self.responses["power"]

    def volume_information(self, *, timeout_seconds: float):
        self.calls.append(("volume", timeout_seconds))
        return self.responses["volume"]

    def playing_content_info(self, *, timeout_seconds: float):
        self.calls.append(("content", timeout_seconds))
        return self.responses["content"]


def test_collect_is_finite_read_only_and_privacy_safe() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    transport = FakeReadTransport(fixture["responses"])
    collector = BraviaReadOnlyCollector(
        transport,
        target_ref="living-room-display",
        timeout_seconds=4,
        clock=lambda: NOW,
    )

    raw = collector.collect()
    rendered = raw.to_json()

    assert transport.calls == [
        ("power", 4),
        ("volume", 4),
        ("content", 4),
    ]
    assert raw.payload["request_count"] == 3
    assert raw.payload["failure_count"] == 0
    assert raw.payload["state"]["power"]["value"] == "active"
    assert raw.payload["state"]["audio"]["outputs"][0]["volume"] == 0
    assert raw.payload["state"]["content"]["source"] == "extInput"
    assert raw.payload["state"]["content"]["private_field_count"] == 1
    assert len(raw.payload["evidence_sha256"]) == 3
    assert all(len(value) == 64 for value in raw.payload["evidence_sha256"])
    assert raw.metadata["retry_count"] == 0
    assert "anonymous-input" not in rendered


def test_one_read_failure_does_not_discard_successful_siblings() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    class FailingVolumeTransport(FakeReadTransport):
        def volume_information(self, *, timeout_seconds: float):
            self.calls.append(("volume", timeout_seconds))
            raise RuntimeError("private-host-and-token")

    collector = BraviaReadOnlyCollector(
        FailingVolumeTransport(fixture["responses"]),
        target_ref="living-room-display",
        clock=lambda: NOW,
    )

    raw = collector.collect()
    rendered = raw.to_json()

    assert raw.payload["failure_count"] == 1
    assert raw.payload["state"]["power"]["quality"] == "good"
    assert raw.payload["state"]["audio"]["quality"] == "missing"
    assert raw.payload["state"]["content"]["quality"] == "good"
    assert "private-host-and-token" not in rendered


def test_timeout_is_strictly_bounded() -> None:
    transport = FakeReadTransport({})

    for invalid in (0, 31):
        try:
            BraviaReadOnlyCollector(
                transport,
                target_ref="living-room-display",
                timeout_seconds=invalid,
            )
        except ValueError as error:
            assert "greater than 0 and at most 30" in str(error)
        else:
            raise AssertionError("invalid timeout was accepted")


def test_clock_must_be_timezone_aware() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    collector = BraviaReadOnlyCollector(
        FakeReadTransport(fixture["responses"]),
        target_ref="living-room-display",
        clock=lambda: datetime(2026, 7, 27, 8, 0),
    )

    try:
        collector.collect()
    except ValueError as error:
        assert "timezone-aware" in str(error)
    else:
        raise AssertionError("naive clock was accepted")
