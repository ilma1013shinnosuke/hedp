from __future__ import annotations

import stat
from pathlib import Path

import pytest

from hedp.adapters.switchbot.private_binding import (
    resolve_unique_device,
    update_private_assignment,
)


def test_resolve_unique_strip_light_uses_exact_device_type() -> None:
    payload = {
        "body": {
            "deviceList": [
                {"deviceType": "Color Bulb", "deviceId": "other"},
                {"deviceType": "Strip Light 3", "deviceId": "private-strip"},
            ]
        }
    }
    assert resolve_unique_device(payload, "Strip Light 3") == "private-strip"


def test_resolve_unique_strip_light_rejects_ambiguous_list() -> None:
    payload = {
        "body": {
            "deviceList": [
                {"deviceType": "Strip Light 3", "deviceId": "one"},
                {"deviceType": "Strip Light 3", "deviceId": "two"},
            ]
        }
    }
    with pytest.raises(ValueError):
        resolve_unique_device(payload, "Strip Light 3")


def test_update_strip_binding_is_atomic_and_keeps_mode(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("OTHER=value\n", encoding="utf-8")
    path.chmod(0o600)

    update_private_assignment(
        path,
        "private-strip",
        name="SWITCHBOT_STRIP_LIGHT_3_DEVICE_ID",
    )

    assert path.read_text(encoding="utf-8") == (
        "OTHER=value\nSWITCHBOT_STRIP_LIGHT_3_DEVICE_ID=private-strip\n"
    )
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_private_binding_installer_fails_closed_without_posix_permissions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / ".env"
    path.write_text("OTHER=value\n", encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setattr(
        "hedp.adapters.switchbot.private_binding.os.name",
        "nt",
    )

    with pytest.raises(OSError, match="platform credential installer"):
        update_private_assignment(
            path,
            "private-strip",
            name="SWITCHBOT_STRIP_LIGHT_3_DEVICE_ID",
        )

    assert path.read_text(encoding="utf-8") == "OTHER=value\n"
