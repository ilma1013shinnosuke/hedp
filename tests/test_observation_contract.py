from __future__ import annotations

from pathlib import Path

import pytest

from hedp.observations import ObservationTime, ObservedValue, Quality


ROOT = Path(__file__).parents[1]
ADAPTER_ROOTS = tuple(
    ROOT / "src" / "hedp" / "adapters" / name
    for name in ("smartledz", "ecocute", "qrio", "miele")
)
FIXTURE_ROOTS = tuple(
    ROOT / "tests" / "fixtures" / name
    for name in ("smartledz", "ecocute", "qrio", "miele")
)


def test_common_quality_vocabulary_is_small_and_complete() -> None:
    assert {quality.value for quality in Quality} == {
        "good",
        "stale",
        "missing",
        "invalid",
        "estimated",
        "unknown",
    }


def test_absence_is_null_and_never_a_fake_good_value() -> None:
    missing = ObservedValue[int](None, Quality.MISSING, "communication_error")

    assert missing.value is None
    with pytest.raises(ValueError, match="must be null"):
        ObservedValue(0, Quality.MISSING, "communication_error")
    with pytest.raises(ValueError, match="must not be null"):
        ObservedValue(None, Quality.GOOD)


def test_observation_time_keeps_source_and_receipt_separate() -> None:
    time = ObservationTime(
        "2026-07-25T00:00:00.123+00:00",
        "2026-07-25T09:00:01+09:00",
    )

    assert time.observed_at.endswith("+00:00")
    assert time.received_at.endswith("+09:00")


def test_reader_adapters_have_no_macos_or_host_path_dependency() -> None:
    forbidden = (
        "AppKit",
        "Foundation",
        "Keychain",
        "launchctl",
        "launchd",
        "osascript",
        "/Users/",
    )
    for root in ADAPTER_ROOTS:
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert not any(item in text for item in forbidden), path


def test_anonymous_fixtures_contain_no_credentials_or_household_network() -> None:
    forbidden = (
        "192.168.",
        "authorization:",
        "bearer ",
        "client_secret",
        "password",
        "refresh_token",
        "access_token",
        "id_token",
        "ssid",
    )
    for root in FIXTURE_ROOTS:
        for path in root.glob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8").casefold()
            assert not any(item in text for item in forbidden), path


def test_read_only_public_interfaces_do_not_expose_action_verbs() -> None:
    from hedp.adapters.ecocute import __all__ as ecocute_api
    from hedp.adapters.miele import __all__ as miele_api
    from hedp.adapters.qrio import __all__ as qrio_api
    from hedp.adapters.smartledz import __all__ as smartledz_api

    forbidden = {
        "delete",
        "lock",
        "pause",
        "restore",
        "run",
        "set",
        "start",
        "stop",
        "unlock",
        "update",
    }
    for api in (ecocute_api, miele_api, qrio_api, smartledz_api):
        for name in api:
            words = name.casefold().replace("-", "_").split("_")
            assert forbidden.isdisjoint(words), name
