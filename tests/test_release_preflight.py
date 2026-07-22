import json
from pathlib import Path
import subprocess

from hedp.operations.preflight import check_cutover_preflight, check_gas_source


ROOT = Path(__file__).parents[1]


def test_gas_preflight_passes_current_source():
    report = check_gas_source(ROOT / "cloud/gas/fusionsolar")
    assert report["status"] == "pass"


def test_cutover_preflight_reports_names_only(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text(".env\n")
    subprocess.run(["git", "add", ".gitignore"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
         "commit", "-qm", "initial"], cwd=tmp_path, check=True,
    )
    names = [
        "SUMICORE_DATABASE_PATH", "SUMICORE_FUSIONSOLAR_BASE_URL",
        "SUMICORE_FUSIONSOLAR_STATION_DN", "SUMICORE_FUSIONSOLAR_USERNAME",
        "SUMICORE_FUSIONSOLAR_PASSWORD", "SUMICORE_FUSIONSOLAR_DEVICE_DNS",
        "SUMICORE_FUSIONSOLAR_BATTERY_DN", "SUMICORE_FUSIONSOLAR_BATTERY_SIGIDS",
        "SUMICORE_SWITCHBOT_HOUSEHOLD_CONFIG_PATH", "SWITCHBOT_TOKEN",
        "SWITCHBOT_SECRET",
    ]
    environment = tmp_path / ".env"
    marker = "never-render-this-value"
    environment.write_text("\n".join(f"{name}={marker}" for name in names))
    environment.chmod(0o600)
    monkeypatch.setattr("hedp.operations.preflight.sys.version_info", (3, 13))
    monkeypatch.setattr("hedp.operations.preflight.ssl.OPENSSL_VERSION", "OpenSSL 3.0")

    report = check_cutover_preflight(tmp_path, environment)

    assert report["status"] == "pass"
    assert marker not in json.dumps(report)
