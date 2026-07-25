import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys


ROOT = Path(__file__).parents[1]


def _daily_health_script_repository(tmp_path: Path) -> tuple[Path, Path]:
    repository = tmp_path / "repository"
    scripts = repository / "scripts"
    command_directory = repository / ".venv" / "bin"
    scripts.mkdir(parents=True)
    command_directory.mkdir(parents=True)
    for name in ("run_daily_health.sh", "run_with_timeout.py", "log_maintenance.sh"):
        shutil.copy(ROOT / "scripts" / name, scripts / name)
    runner = scripts / "run_daily_health.sh"
    runner.chmod(0o755)
    python = command_directory / "python"
    python.symlink_to(sys.executable)
    hedp = command_directory / "hedp"
    hedp.write_text(
        "#!/bin/bash\n"
        "printf '%s\\n' \"$1\" >> \"${CALL_LOG}\"\n"
    )
    hedp.chmod(0o755)
    return repository, runner


def test_five_minute_script_collects_realtime_and_current_alarms():
    script = (ROOT / "scripts" / "run_device_realtime.sh").read_text()
    assert "collect-realtime" in script
    assert "collect-modbus" in script
    assert "FUSIONSOLAR_REALTIME_MODE" in script
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
    assert "run_with_timeout.py" in runner
    assert "SUMICORE_DAILY_HEALTH_TIMEOUT_SECONDS" in runner
    assert "HEDP_DAILY_HEALTH_TIMEOUT_SECONDS" in runner
    assert "between 1 and 300 seconds" in runner
    assert "<key>Hour</key><integer>4</integer>" in installer
    assert "<key>Minute</key><integer>10</integer>" in installer
    assert "daily-health.out.log" in installer
    assert "daily-health.err.log" in installer
    assert "chmod 600" in installer
    assert "switch_macos_launchd_job.sh" in installer
    assert "HEDP_FUSIONSOLAR_PASSWORD" not in installer
    assert "com.hedp.database.lock" in runner


def test_daily_health_runner_rejects_an_unbounded_timeout(tmp_path):
    _, runner = _daily_health_script_repository(tmp_path)
    call_log = tmp_path / "calls.log"

    result = subprocess.run(
        [str(runner)],
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "CALL_LOG": str(call_log),
            "HEDP_DATABASE_LOCK_DIRECTORY": str(tmp_path / "database.lock"),
            "HEDP_DAILY_HEALTH_TIMEOUT_SECONDS": "301",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "between 1 and 300 seconds" in result.stderr
    assert not call_log.exists()


def test_daily_health_runner_uses_the_bounded_timeout_wrapper(tmp_path):
    _, runner = _daily_health_script_repository(tmp_path)
    call_log = tmp_path / "calls.log"

    result = subprocess.run(
        [str(runner)],
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "CALL_LOG": str(call_log),
            "HEDP_DATABASE_LOCK_DIRECTORY": str(tmp_path / "database.lock"),
            "HEDP_DAILY_HEALTH_TIMEOUT_SECONDS": "1",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert call_log.read_text().splitlines() == ["daily-health"]


def test_switchbot_job_runs_hourly_at_minute_five_without_plist_secrets():
    runner = (ROOT / "scripts" / "run_switchbot_hourly.sh").read_text()
    installer = (
        ROOT / "scripts" / "install_macos_switchbot_launchd.sh"
    ).read_text()
    assert "switchbot collect" in runner
    assert "run_with_env.py" in runner
    assert "source .env" not in runner
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


def test_uninstaller_covers_every_current_and_legacy_job():
    script = (ROOT / "scripts" / "uninstall_macos_launchd.sh").read_text()

    for job in (
        "collect",
        "device-realtime",
        "equipment",
        "switchbot",
        "daily-health",
    ):
        assert job in script
    assert "com.sumicore" in script
    assert "com.hedp" in script


def test_every_runner_uses_common_log_rotation():
    runners = {
        "run_daily.sh": "collect",
        "run_device_realtime.sh": "device-realtime",
        "run_equipment_daily.sh": "equipment",
        "run_switchbot_hourly.sh": "switchbot",
        "run_daily_health.sh": "daily-health",
    }
    for name, job in runners.items():
        script = (ROOT / "scripts" / name).read_text()
        assert 'source "${SCRIPT_DIR}/log_maintenance.sh"' in script
        assert f"sumicore_rotate_job_logs {job}" in script


def test_common_log_rotation_keeps_two_generations(tmp_path):
    home = tmp_path / "home"
    logs = home / "Library" / "Logs" / "hedp"
    logs.mkdir(parents=True)
    current = logs / "fixture.err.log"
    current.write_text("current")
    (logs / "fixture.err.log.1").write_text("previous")

    environment = {**os.environ, "HOME": str(home)}
    subprocess.run(
        [
            "bash",
            "-c",
            (
                f"source {ROOT / 'scripts' / 'log_maintenance.sh'}; "
                "sumicore_rotate_job_logs fixture 1 2"
            ),
        ],
        check=True,
        env=environment,
    )

    assert current.read_text() == ""
    assert (logs / "fixture.err.log.1").read_text() == "current"
    assert (logs / "fixture.err.log.2").read_text() == "previous"


def test_modbus_only_installer_omits_cloud_credentials(tmp_path):
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/bin/bash\n"
        "if [[ \"$1\" == \"print\" && \"$2\" == *com.hedp.* ]]; then "
        "exit 1; fi\n"
        "exit 0\n"
    )
    launchctl.chmod(0o755)
    environment = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
        "HEDP_FUSIONSOLAR_MODBUS_HOST": "192.0.2.1",
        "HEDP_FUSIONSOLAR_MODBUS_PORT": "502",
        "HEDP_FUSIONSOLAR_MODBUS_UNIT_ID": "1",
        "HEDP_FUSIONSOLAR_MODBUS_EXPECTED_SERIAL": "fixture",
        "HEDP_FUSIONSOLAR_REALTIME_MODE": "modbus",
    }

    subprocess.run(
        [str(ROOT / "scripts" / "install_macos_device_realtime_launchd.sh")],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )

    plist = plistlib.loads(
        (
            home
            / "Library"
            / "LaunchAgents"
            / "com.sumicore.device-realtime.plist"
        ).read_bytes()
    )
    values = plist["EnvironmentVariables"]
    assert values["HEDP_FUSIONSOLAR_REALTIME_MODE"] == "modbus"
    assert "HEDP_FUSIONSOLAR_PASSWORD" not in values
    assert "HEDP_FUSIONSOLAR_USERNAME" not in values
    assert "HEDP_FUSIONSOLAR_DEVICE_DNS" not in values


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
