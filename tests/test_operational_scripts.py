from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_five_minute_script_collects_realtime_and_current_alarms():
    script = (ROOT / "scripts" / "run_device_realtime.sh").read_text()
    assert "collect-realtime" in script
    assert "com.hedp.device-realtime.lock" in script


def test_equipment_job_runs_battery_dc_at_0310():
    runner = (ROOT / "scripts" / "run_equipment_daily.sh").read_text()
    installer = (
        ROOT / "scripts" / "install_macos_equipment_launchd.sh"
    ).read_text()
    assert "collect-battery-dc" in runner
    assert "com.hedp.equipment.lock" in runner
    assert "<integer>3</integer>" in installer
    assert "<integer>10</integer>" in installer
    assert "chmod 600" in installer


def test_daily_health_job_runs_json_at_0320_without_credentials():
    runner = (ROOT / "scripts" / "run_daily_health.sh").read_text()
    installer = (
        ROOT / "scripts" / "install_macos_daily_health_launchd.sh"
    ).read_text()
    assert "daily-health --json" in runner
    assert "<integer>3</integer>" in installer
    assert "<integer>20</integer>" in installer
    assert "daily-health.out.log" in installer
    assert "daily-health.err.log" in installer
    assert "chmod 600" in installer
    assert "plutil -lint" in installer
    assert "HEDP_FUSIONSOLAR_PASSWORD" not in installer


def test_switchbot_job_runs_hourly_at_minute_five_without_plist_secrets():
    runner = (ROOT / "scripts" / "run_switchbot_hourly.sh").read_text()
    installer = (
        ROOT / "scripts" / "install_macos_switchbot_launchd.sh"
    ).read_text()
    assert "switchbot collect" in runner
    assert "source .env" in runner
    assert "set -x" not in runner
    assert "com.hedp.switchbot.lock" in runner
    assert "<key>Minute</key><integer>5</integer>" in installer
    assert "SWITCHBOT_TOKEN" not in installer
    assert "SWITCHBOT_SECRET" not in installer
    assert "chmod 600" in installer
    assert "plutil -lint" in installer
