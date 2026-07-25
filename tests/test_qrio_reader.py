from __future__ import annotations

import json
from pathlib import Path

import pytest

from hedp.adapters.qrio import (
    BatteryState,
    LockAction,
    LockPosition,
    QrioReader,
    normalize_health,
    normalize_history,
    normalize_status,
)
from hedp.observations import ObservationTime, Quality


FIXTURE = Path(__file__).parent / "fixtures" / "qrio" / "read_responses_v1.json"
TIME = ObservationTime(
    "2026-07-25T09:00:01+09:00",
    "2026-07-25T09:00:01+09:00",
)


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_normalizes_status_without_raw_lock_identifier() -> None:
    status = normalize_status(
        _fixture()["status"],
        target_ref="entrance-lock",
        time=TIME,
    )

    assert status.position.value == LockPosition.LOCKED
    assert status.position.quality == Quality.GOOD
    assert "entrance-lock" not in repr(status)


def test_normalizes_health_and_omits_name_and_identifiers() -> None:
    fixture = _fixture()
    batch = normalize_health(
        fixture["health"],
        aliases={"fixture-lock-001": "entrance-lock"},
        time=TIME,
    )

    assert batch.quality == Quality.GOOD
    health = batch.items[0]
    assert health.battery_a.value == BatteryState.OK
    assert health.battery_b.value == BatteryState.LOW
    assert health.hub_registered.value is True
    assert health.auto_lock_enabled.value is True
    rendered = repr(batch)
    assert "fixture-lock-001" not in rendered
    assert "fixture-hub-001" not in rendered
    assert "anonymous" not in rendered


def test_history_preserves_event_time_and_hashes_vendor_event_id() -> None:
    batch = normalize_history(
        _fixture()["history"],
        target_ref="entrance-lock",
        received_at="2026-07-25T09:00:01+09:00",
    )

    assert batch.quality == Quality.GOOD
    assert batch.items[0].action.value == LockAction.LOCKED
    assert batch.items[0].time.observed_at == "2026-07-25T00:00:00.000+00:00"
    rendered = repr(batch)
    assert "fixture-event-001" not in rendered
    assert "entrance-lock" not in rendered
    assert "omitted" not in rendered


@pytest.mark.parametrize(
    ("response", "quality"),
    [
        ({}, Quality.MISSING),
        ({"main_lock": 9}, Quality.UNKNOWN),
        ({"main_lock": "2"}, Quality.UNKNOWN),
        ([], Quality.INVALID),
    ],
)
def test_status_failure_quality_is_explicit(
    response: object,
    quality: Quality,
) -> None:
    status = normalize_status(response, target_ref="entrance-lock", time=TIME)

    assert status.position.value is None
    assert status.position.quality == quality


def test_unknown_lock_is_not_emitted_from_health() -> None:
    batch = normalize_health(_fixture()["health"], aliases={}, time=TIME)

    assert batch.items == ()
    assert batch.quality == Quality.UNKNOWN
    assert batch.unmapped_count == 1


def test_reader_interface_contains_no_operation_method() -> None:
    class FakeTransport:
        def status(self, source_lock_id: str) -> object:
            return {"main_lock": 2}

        def health(self) -> object:
            return {"data": []}

        def history(self, source_lock_id: str, *, page: int) -> object:
            return {"display_logs": [], "page": page}

    reader = QrioReader(FakeTransport())

    assert reader.status("fixture") == {"main_lock": 2}
    assert reader.history("fixture", page=2)["page"] == 2
    assert not hasattr(reader, "lock")
    assert not hasattr(reader, "unlock")


def test_fixture_contains_only_synthetic_identifiers_and_no_credentials() -> None:
    text = FIXTURE.read_text(encoding="utf-8").casefold()

    for forbidden in (
        "192.168.",
        "password",
        "token",
        "cookie",
        "authorization",
        "ssid",
        "serial",
    ):
        assert forbidden not in text
    assert "fixture-" in text
