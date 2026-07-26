from __future__ import annotations

import pytest

from hedp.adapters.smartledz import SmartLedzConfiguration


def test_smartledz_configuration_uses_portable_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUMICORE_SMARTLEDZ_HOST", "fixture-gateway.invalid")
    monkeypatch.setenv("SUMICORE_SMARTLEDZ_PORT", "1234")
    monkeypatch.setenv("SUMICORE_SMARTLEDZ_TIMEOUT_SECONDS", "7")

    configuration = SmartLedzConfiguration.from_environment()

    assert configuration.port == 1234
    assert configuration.timeout_seconds == 7
    assert "fixture-gateway.invalid" not in repr(configuration)


def test_smartledz_configuration_rejects_unbounded_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUMICORE_SMARTLEDZ_HOST", "fixture-gateway.invalid")
    monkeypatch.setenv("SUMICORE_SMARTLEDZ_PORT", "1234")
    monkeypatch.setenv("SUMICORE_SMARTLEDZ_TIMEOUT_SECONDS", "31")

    with pytest.raises(RuntimeError, match="timeout"):
        SmartLedzConfiguration.from_environment()
