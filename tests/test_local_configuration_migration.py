from pathlib import Path
import runpy


ROOT = Path(__file__).parents[1]
MIGRATION = runpy.run_path(str(ROOT / "scripts" / "migrate_local_configuration.py"))


def test_legacy_switchbot_configuration_can_be_reconstructed_without_values_in_code():
    payload = MIGRATION["switchbot_configuration"](ROOT)

    assert len(payload["filename_device_ids"]) == 11
    assert len(payload["location_history"]) == 13
    assert len(payload["name_history"]) == 1
    assert all(
        {"device_id", "location", "purpose", "valid_from"} <= set(item)
        for item in payload["location_history"]
    )


def test_environment_update_preserves_unrelated_values_and_private_mode(tmp_path):
    environment_path = tmp_path / ".env"
    environment_path.write_text("SWITCHBOT_TOKEN='existing-test-value'\n")
    environment_path.chmod(0o600)

    MIGRATION["update_environment_file"](
        environment_path,
        {"SUMICORE_DATABASE_PATH": "/example/data.db"},
    )

    content = environment_path.read_text()
    assert "SWITCHBOT_TOKEN='existing-test-value'" in content
    assert "SUMICORE_DATABASE_PATH=/example/data.db" in content
    assert environment_path.stat().st_mode & 0o777 == 0o600
