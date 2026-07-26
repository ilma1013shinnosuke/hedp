from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from hedp.adapters.qrio import QrioReadOnlyCollector, QrioReader


FIXTURE = Path(__file__).parent / "fixtures" / "qrio" / "read_responses_v1.json"
NOW = datetime.fromisoformat("2026-07-26T10:00:00+09:00")


class FakeTransport:
    def __init__(self, fixture: dict[str, object]) -> None:
        self.fixture = fixture
        self.calls: list[tuple[str, str | int | None]] = []

    def status(self, source_lock_id: str) -> object:
        self.calls.append(("status", source_lock_id))
        return self.fixture["status"]

    def health(self) -> object:
        self.calls.append(("health", None))
        return self.fixture["health"]

    def history(self, source_lock_id: str, *, page: int) -> object:
        self.calls.append(("history", page))
        return self.fixture["history"]


def test_collector_produces_privacy_safe_status_health_and_history() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    transport = FakeTransport(fixture)
    collector = QrioReadOnlyCollector(
        QrioReader(transport),
        source_lock_id="fixture-lock-001",
        target_ref="entrance-lock",
        clock=lambda: NOW,
    )

    raw = collector.collect()
    rendered = raw.to_json()

    assert raw.source == "qrio_read_only"
    assert raw.payload["status"]["value"] == "locked"
    assert raw.payload["health"]["items"][0]["battery_b"]["value"] == "low"
    assert raw.payload["history"]["items"][0]["action"]["value"] == "locked"
    assert len(raw.payload["history"]["items"][0]["dedupe_key"]) == 64
    assert raw.metadata["raw_policy"] == (
        "fingerprint_only_due_to_household_secrets"
    )
    assert transport.calls == [
        ("status", "fixture-lock-001"),
        ("health", None),
        ("history", 1),
    ]
    for secret in (
        "fixture-lock-001",
        "fixture-hub-001",
        "fixture-event-001",
        "anonymous",
        "omitted",
    ):
        assert secret not in rendered


def test_collector_preserves_unknown_quality_without_guessing() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fixture["status"] = {"main_lock": 99}
    collector = QrioReadOnlyCollector(
        QrioReader(FakeTransport(fixture)),
        source_lock_id="fixture-lock-001",
        target_ref="entrance-lock",
        clock=lambda: NOW,
    )

    raw = collector.collect()

    assert raw.payload["status"] == {
        "value": None,
        "quality": "unknown",
        "reason": "main_lock_unknown",
        "last_success_at": None,
    }
