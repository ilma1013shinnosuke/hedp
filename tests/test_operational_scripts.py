import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[1]


def test_five_minute_script_collects_realtime_and_current_alarms():
    script = (ROOT / "scripts" / "run_device_realtime.sh").read_text()
    assert "collect-realtime" in script
    assert "com.hedp.database.lock" in script


def test_equipment_job_runs_battery_dc_at_0310():
    runner = (ROOT / "scripts" / "run_equipment_daily.sh").read_text()
    installer = (
        ROOT / "scripts" / "install_macos_equipment_launchd.sh"
    ).read_text()
    assert "collect-battery-dc" in runner
    assert "com.hedp.database.lock" in runner
    assert "<integer>3</integer>" in installer
    assert "<integer>10</integer>" in installer
    assert "chmod 600" in installer


def test_daily_health_job_runs_json_at_0410_without_credentials():
    runner = (ROOT / "scripts" / "run_daily_health.sh").read_text()
    installer = (
        ROOT / "scripts" / "install_macos_daily_health_launchd.sh"
    ).read_text()
    assert "daily-health --json" in runner
    assert "<key>Hour</key><integer>4</integer>" in installer
    assert "<key>Minute</key><integer>10</integer>" in installer
    assert "daily-health.out.log" in installer
    assert "daily-health.err.log" in installer
    assert "chmod 600" in installer
    assert "switch_macos_launchd_job.sh" in installer
    assert "HEDP_FUSIONSOLAR_PASSWORD" not in installer
    assert "com.hedp.database.lock" in runner


def test_switchbot_job_runs_hourly_at_minute_five_without_plist_secrets():
    runner = (ROOT / "scripts" / "run_switchbot_hourly.sh").read_text()
    installer = (
        ROOT / "scripts" / "install_macos_switchbot_launchd.sh"
    ).read_text()
    assert "switchbot collect" in runner
    assert "source .env" in runner
    assert "set -x" not in runner
    assert "com.hedp.database.lock" in runner
    assert "<key>Minute</key><integer>5</integer>" in installer
    assert "SWITCHBOT_TOKEN" not in installer
    assert "SWITCHBOT_SECRET" not in installer
    assert "chmod 600" in installer
    assert "switch_macos_launchd_job.sh" in installer


def test_all_database_jobs_share_one_lock():
    runners = [
        "run_daily.sh",
        "run_device_realtime.sh",
        "run_equipment_daily.sh",
        "run_switchbot_hourly.sh",
        "run_daily_health.sh",
    ]
    for name in runners:
        script = (ROOT / "scripts" / name).read_text()
        assert "com.hedp.database.lock" in script
        assert "HEDP_DATABASE_LOCK_DIRECTORY" in script
        assert "SUMICORE_DATABASE_LOCK_DIRECTORY" in script


def test_all_launchd_installers_make_logs_private():
    installers = [
        "install_macos_launchd.sh",
        "install_macos_device_realtime_launchd.sh",
        "install_macos_equipment_launchd.sh",
        "install_macos_daily_health_launchd.sh",
        "install_macos_switchbot_launchd.sh",
    ]
    for name in installers:
        script = (ROOT / "scripts" / name).read_text()
        assert "touch" in script
        assert "chmod 600" in script
        assert ".out.log" in script
        assert ".err.log" in script


def test_installers_switch_from_legacy_to_sumicore_labels():
    installers = [
        "install_macos_launchd.sh",
        "install_macos_device_realtime_launchd.sh",
        "install_macos_equipment_launchd.sh",
        "install_macos_daily_health_launchd.sh",
        "install_macos_switchbot_launchd.sh",
    ]
    for name in installers:
        script = (ROOT / "scripts" / name).read_text()
        assert 'LABEL="com.sumicore.' in script
        assert 'LEGACY_LABEL="com.hedp.' in script
        assert "switch_macos_launchd_job.sh" in script


def test_launchd_switcher_validates_and_restores_legacy_job():
    script = (ROOT / "scripts" / "switch_macos_launchd_job.sh").read_text()
    assert 'plutil -lint "${NEW_PLIST}"' in script
    assert 'bootout "${DOMAIN}/${LEGACY_LABEL}"' in script
    assert 'bootstrap "${DOMAIN}" "${LEGACY_PLIST}"' in script
    assert 'print "${DOMAIN}/${NEW_LABEL}"' in script


def _write_fake_command(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text("#!/bin/bash\nset -eu\n" + body)
    path.chmod(0o755)


def _launchd_test_environment(tmp_path: Path, *, fail_new: bool) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_command(bin_dir, "uname", 'printf "Darwin\\n"\n')
    _write_fake_command(bin_dir, "id", 'printf "501\\n"\n')
    _write_fake_command(bin_dir, "plutil", 'printf "plutil %s\\n" "$*" >> "$CALL_LOG"\n')
    _write_fake_command(
        bin_dir,
        "launchctl",
        """printf "launchctl %s\\n" "$*" >> "$CALL_LOG"
if [[ "$1" == "print" ]]; then
    exit 0
fi
if [[ "$1" == "bootstrap" && "$3" == *"com.sumicore.test.plist" \
      && "${FAIL_NEW_BOOTSTRAP}" == "1" ]]; then
    exit 1
fi
exit 0
""",
    )
    environment = os.environ.copy()
    environment["PATH"] = f"{bin_dir}:{environment['PATH']}"
    environment["CALL_LOG"] = str(tmp_path / "calls.log")
    environment["FAIL_NEW_BOOTSTRAP"] = "1" if fail_new else "0"
    return environment


def test_launchd_switcher_restores_legacy_job_after_bootstrap_failure(tmp_path):
    new_plist = tmp_path / "com.sumicore.test.plist"
    legacy_plist = tmp_path / "com.hedp.test.plist"
    new_plist.write_text("new")
    legacy_plist.write_text("legacy")
    environment = _launchd_test_environment(tmp_path, fail_new=True)

    result = subprocess.run(
        [
            str(ROOT / "scripts" / "switch_macos_launchd_job.sh"),
            "com.sumicore.test",
            str(new_plist),
            "com.hedp.test",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    calls = Path(environment["CALL_LOG"]).read_text()
    assert result.returncode == 1
    assert f"bootstrap gui/501 {legacy_plist}" in calls
    assert "kickstart -k gui/501/com.hedp.test" in calls
    assert "Restored com.hedp.test" in result.stderr


def test_launchd_switcher_keeps_new_job_when_bootstrap_succeeds(tmp_path):
    new_plist = tmp_path / "com.sumicore.test.plist"
    (tmp_path / "com.hedp.test.plist").write_text("legacy")
    new_plist.write_text("new")
    environment = _launchd_test_environment(tmp_path, fail_new=False)

    result = subprocess.run(
        [
            str(ROOT / "scripts" / "switch_macos_launchd_job.sh"),
            "com.sumicore.test",
            str(new_plist),
            "com.hedp.test",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    calls = Path(environment["CALL_LOG"]).read_text()
    assert result.returncode == 0
    assert f"bootstrap gui/501 {new_plist}" in calls
    assert "kickstart -k gui/501/com.sumicore.test" in calls
    assert "bootstrap gui/501 " + str(tmp_path / "com.hedp.test.plist") not in calls


def test_shell_environment_compatibility_prefers_sumicore(tmp_path):
    helper = ROOT / "scripts" / "environment_compatibility.sh"
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            'source "$1"; '
            "SUMICORE_DATABASE_PATH=current HEDP_DATABASE_PATH=legacy; "
            "sumicore_apply_legacy_environment DATABASE_PATH; "
            'test "$HEDP_DATABASE_PATH" = current',
            "test",
            str(helper),
        ],
        check=False,
    )
    assert result.returncode == 0
