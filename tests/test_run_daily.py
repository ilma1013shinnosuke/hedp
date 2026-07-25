import os
from pathlib import Path
import shutil
import stat
import subprocess
import time

import pytest


def _daily_script_repository(tmp_path: Path) -> tuple[Path, Path]:
    repository = tmp_path / "repository"
    scripts = repository / "scripts"
    command_directory = repository / ".venv" / "bin"
    scripts.mkdir(parents=True)
    command_directory.mkdir(parents=True)
    run_daily = scripts / "run_daily.sh"
    shutil.copy(
        Path(__file__).parents[1] / "scripts" / "run_daily.sh",
        run_daily,
    )
    shutil.copy(
        Path(__file__).parents[1] / "scripts" / "run_with_timeout.py",
        scripts / "run_with_timeout.py",
    )
    shutil.copy(
        Path(__file__).parents[1] / "scripts" / "log_maintenance.sh",
        scripts / "log_maintenance.sh",
    )
    shutil.copy(
        Path(__file__).parents[1] / "scripts" / "operational_metrics.sh",
        scripts / "operational_metrics.sh",
    )
    run_daily.chmod(0o755)
    hedp = command_directory / "hedp"
    hedp.write_text(
        "#!/bin/bash\n"
        "printf '%s\\n' \"$1\" >> \"${CALL_LOG}\"\n"
        "if [[ \"$1\" == \"${FAIL_COMMAND:-}\" ]]; then exit 1; fi\n"
    )
    hedp.chmod(0o755)
    return repository, run_daily


def test_run_daily_collects_backs_up_and_retains_latest_compressed(tmp_path) -> None:
    repository, run_daily = _daily_script_repository(tmp_path)
    backups = repository / "backups"
    backups.mkdir()
    backup_names = [
        f"hedp-202601{day:02d}-030000.db" for day in range(1, 32)
    ]
    for name in backup_names:
        (backups / name).touch()
    invalid_backup = backups / "hedp-old.db"
    invalid_backup.touch()
    stale_partial = backups / ".hedp-20260131-030000.db.old.partial"
    stale_partial.touch()
    old_time = time.time() - 2 * 60 * 60
    os.utime(stale_partial, (old_time, old_time))
    recent_partial = backups / ".hedp-20260131-040000.db.new.partial"
    recent_partial.touch()
    database = repository / "hedp.db"
    database.touch()
    call_log = tmp_path / "calls.log"

    result = subprocess.run(
        [str(run_daily)],
        env={
            **os.environ,
            "HEDP_DATABASE_LOCK_DIRECTORY": str(tmp_path / "database.lock"),
            "CALL_LOG": str(call_log),
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert call_log.read_text().splitlines() == [
        "collect",
        "backfill-missing",
        "backfill-energy-balance",
        "quality",
        "quality-energy-balance",
        "backup",
    ]
    assert sorted(path.name for path in backups.glob("hedp-*.db")) == [
        invalid_backup.name,
    ]
    compressed_backups = sorted(backups.glob("hedp-*.db.gz"))
    assert [path.name for path in compressed_backups] == [
        backup_names[-1] + ".gz",
    ]
    assert stat.S_IMODE(compressed_backups[0].stat().st_mode) == 0o600
    assert not stale_partial.exists()
    assert recent_partial.exists()
    assert database.is_file()


def test_run_daily_preserves_partial_data_and_backs_up_after_failure(tmp_path) -> None:
    _, run_daily = _daily_script_repository(tmp_path)
    call_log = tmp_path / "calls.log"

    result = subprocess.run(
        [str(run_daily)],
        env={
            **os.environ,
            "HEDP_DATABASE_LOCK_DIRECTORY": str(tmp_path / "database.lock"),
            "CALL_LOG": str(call_log),
            "FAIL_COMMAND": "collect",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert call_log.read_text().splitlines() == [
        "collect",
        "backfill-missing",
        "backfill-energy-balance",
        "quality",
        "quality-energy-balance",
        "backup",
    ]


def test_run_daily_fails_when_backup_fails(tmp_path) -> None:
    _, run_daily = _daily_script_repository(tmp_path)
    call_log = tmp_path / "calls.log"

    result = subprocess.run(
        [str(run_daily)],
        env={
            **os.environ,
            "HEDP_DATABASE_LOCK_DIRECTORY": str(tmp_path / "database.lock"),
            "CALL_LOG": str(call_log),
            "FAIL_COMMAND": "backup",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert call_log.read_text().splitlines() == [
        "collect",
        "backfill-missing",
        "backfill-energy-balance",
        "quality",
        "quality-energy-balance",
        "backup",
    ]


def test_run_daily_skips_when_lock_is_held(tmp_path) -> None:
    _, run_daily = _daily_script_repository(tmp_path)
    lock = tmp_path / "com.hedp.database.lock"
    lock.mkdir()
    call_log = tmp_path / "calls.log"

    result = subprocess.run(
        [str(run_daily)],
        env={
            **os.environ,
            "HEDP_DATABASE_LOCK_DIRECTORY": str(lock),
            "CALL_LOG": str(call_log),
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "already running" in result.stderr
    assert not call_log.exists()


@pytest.mark.parametrize("retention", ["0", "-1", "invalid"])
def test_run_daily_rejects_invalid_retention_before_touching_backups(
    tmp_path: Path,
    retention: str,
) -> None:
    repository, run_daily = _daily_script_repository(tmp_path)
    backups = repository / "backups"
    backups.mkdir()
    existing = backups / "hedp-20260724-030000.db.gz"
    existing.write_bytes(b"existing-backup")
    before = existing.read_bytes()
    call_log = tmp_path / "calls.log"
    lock = tmp_path / "database.lock"

    result = subprocess.run(
        [str(run_daily)],
        env={
            **os.environ,
            "HEDP_DATABASE_LOCK_DIRECTORY": str(lock),
            "HEDP_BACKUP_RETENTION_COUNT": retention,
            "CALL_LOG": str(call_log),
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "retention count" in result.stderr.casefold()
    assert existing.read_bytes() == before
    assert not call_log.exists()
    assert not lock.exists()
