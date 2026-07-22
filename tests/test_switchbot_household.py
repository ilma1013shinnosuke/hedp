import json

import pytest

from hedp.adapters.switchbot.household import SwitchBotHouseholdConfiguration


def test_household_configuration_loads_valid_file(tmp_path, monkeypatch):
    path = tmp_path / "switchbot.json"
    path.write_text(
        json.dumps(
            {
                "filename_device_ids": {"リビング": "living-sensor"},
                "location_history": [
                    {
                        "device_id": "living-sensor",
                        "location": "リビング",
                        "purpose": "温湿度",
                        "valid_from": "2026-01-01",
                    }
                ],
                "name_history": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    monkeypatch.setenv("HEDP_SWITCHBOT_HOUSEHOLD_CONFIG_PATH", str(path))

    configuration = SwitchBotHouseholdConfiguration.from_environment()

    assert configuration.filename_device_ids == {"リビング": "living-sensor"}
    assert configuration.location_history[0]["location"] == "リビング"


def test_household_configuration_is_optional(monkeypatch):
    monkeypatch.delenv("HEDP_SWITCHBOT_HOUSEHOLD_CONFIG_PATH", raising=False)
    assert SwitchBotHouseholdConfiguration.from_environment() == (
        SwitchBotHouseholdConfiguration()
    )


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"filename_device_ids": []}, "filename_device_ids"),
        ({"location_history": [{}]}, "location_history"),
        ({"name_history": [{"device_id": "x"}]}, "name_history"),
    ],
)
def test_household_configuration_rejects_invalid_shape(
    tmp_path, payload, expected
):
    path = tmp_path / "switchbot.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(RuntimeError, match=expected):
        SwitchBotHouseholdConfiguration.from_file(path)


def test_household_configuration_requires_private_permissions(tmp_path):
    path = tmp_path / "switchbot.json"
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o644)
    with pytest.raises(RuntimeError, match="0600"):
        SwitchBotHouseholdConfiguration.from_file(path)
