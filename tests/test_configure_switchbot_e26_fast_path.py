from __future__ import annotations

import stat
from pathlib import Path

import pytest

from hedp.adapters.switchbot.private_binding import update_private_assignment
from scripts.configure_switchbot_e26_fast_path import resolve_unique_e26


def test_resolve_unique_e26_uses_exact_device_type() -> None:
    payload = {
        "body": {
            "deviceList": [
                {"deviceType": "Color Bulb", "deviceId": "private-id"},
                {"deviceType": "Strip Light 3", "deviceId": "other-id"},
            ]
        }
    }
    assert resolve_unique_e26(payload) == "private-id"


def test_resolve_unique_e26_rejects_ambiguous_list() -> None:
    payload = {
        "body": {
            "deviceList": [
                {"deviceType": "Color Bulb", "deviceId": "one"},
                {"deviceType": "Color Bulb", "deviceId": "two"},
            ]
        }
    }
    with pytest.raises(ValueError):
        resolve_unique_e26(payload)


def test_update_private_assignment_is_atomic_and_keeps_mode(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("OTHER=value\nSWITCHBOT_E26_DEVICE_ID=old\n", encoding="utf-8")
    path.chmod(0o600)

    update_private_assignment(
        path,
        "new-private-id",
        name="SWITCHBOT_E26_DEVICE_ID",
    )

    assert path.read_text(encoding="utf-8") == (
        "OTHER=value\nSWITCHBOT_E26_DEVICE_ID=new-private-id\n"
    )
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
