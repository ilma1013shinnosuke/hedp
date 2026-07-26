from __future__ import annotations

import pytest

from hedp.adapters.miele import MieleConfiguration


def test_miele_configuration_uses_sumicore_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "SUMICORE_MIELE_DEVICES_URL": "https://fixture.invalid/v1/devices",
        "SUMICORE_MIELE_EVENTS_URL": "https://fixture.invalid/v1/events",
        "SUMICORE_MIELE_ACCESS_TOKEN": "fixture-token",
        "SUMICORE_MIELE_DEVICE_ID": "fixture-device",
        "SUMICORE_MIELE_TARGET_REF": "laundry",
        "SUMICORE_MIELE_REST_TIMEOUT_SECONDS": "12",
        "SUMICORE_MIELE_SSE_TIMEOUT_SECONDS": "20",
        "SUMICORE_MIELE_MAXIMUM_EVENTS": "8",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
        monkeypatch.delenv(name.replace("SUMICORE_", "HEDP_"), raising=False)

    configuration = MieleConfiguration.from_environment()

    assert configuration.devices_url.endswith("/v1/devices")
    assert configuration.target_ref == "laundry"
    assert configuration.rest_timeout_seconds == 12
    assert configuration.sse_timeout_seconds == 20
    assert configuration.maximum_events == 8
    assert "fixture-token" not in repr(configuration)
    assert "fixture-device" not in repr(configuration)


def test_miele_configuration_rejects_unbounded_sse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for suffix, value in {
        "DEVICES_URL": "https://fixture.invalid/v1/devices",
        "EVENTS_URL": "https://fixture.invalid/v1/events",
        "ACCESS_TOKEN": "fixture-token",
        "DEVICE_ID": "fixture-device",
        "SSE_TIMEOUT_SECONDS": "301",
    }.items():
        monkeypatch.setenv(f"SUMICORE_MIELE_{suffix}", value)

    with pytest.raises(RuntimeError, match="SSE timeout"):
        MieleConfiguration.from_environment()
