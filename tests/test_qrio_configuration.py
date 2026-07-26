from __future__ import annotations

import pytest

from hedp.adapters.qrio import QrioConfiguration


def _set_required(monkeypatch: pytest.MonkeyPatch) -> None:
    for suffix, value in {
        "STATUS_URL_TEMPLATE": "https://fixture.invalid/status/{lock_id}",
        "HEALTH_URL": "https://fixture.invalid/health",
        "HISTORY_URL_TEMPLATE": (
            "https://fixture.invalid/history/{lock_id}?page={page}"
        ),
        "AUTHORIZATION": "fixture-authorization",
        "LOCK_ID": "fixture-lock",
    }.items():
        monkeypatch.setenv(f"SUMICORE_QRIO_{suffix}", value)


def test_qrio_configuration_hides_household_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv("SUMICORE_QRIO_TARGET_REF", "entrance")
    monkeypatch.setenv("SUMICORE_QRIO_TIMEOUT_SECONDS", "12")

    configuration = QrioConfiguration.from_environment()

    assert configuration.target_ref == "entrance"
    assert configuration.timeout_seconds == 12
    rendered = repr(configuration)
    assert "fixture-authorization" not in rendered
    assert "fixture-lock" not in rendered
    assert "fixture.invalid" not in rendered


def test_qrio_configuration_rejects_unbounded_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv(
        "SUMICORE_QRIO_MAXIMUM_RESPONSE_BYTES", str(4 * 1024 * 1024 + 1)
    )

    with pytest.raises(RuntimeError, match="byte limit"):
        QrioConfiguration.from_environment()


def test_qrio_configuration_rejects_empty_required_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv("SUMICORE_QRIO_AUTHORIZATION", " ")

    with pytest.raises(RuntimeError, match="Missing required|must not be empty"):
        QrioConfiguration.from_environment()
