from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from hedp.storage import Storage


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "record_operational_metric.py"


def _environment(state_home: Path, **values: str) -> dict[str, str]:
    environment = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "XDG_STATE_HOME": str(state_home),
        **values,
    }
    environment.pop("SUMICORE_DATABASE_PATH", None)
    environment.pop("HEDP_DATABASE_PATH", None)
    environment.update(values)
    return environment


def _journal_record(state_home: Path) -> dict[str, object]:
    path = state_home / "sumicore" / "operational-metrics.jsonl"
    return json.loads(path.read_text(encoding="utf-8"))


def test_operation_cli_accepts_only_fixed_values_and_prints_nothing(tmp_path: Path) -> None:
    state_home = tmp_path / "state"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "operation",
            "daily",
            "completed",
            "1.2",
            "none",
        ],
        env=_environment(state_home),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert _journal_record(state_home) == {
        "date": _journal_record(state_home)["date"],
        "duration": "1_to_5s",
        "failure_category": "none",
        "job": "daily",
        "kind": "operation",
        "outcome": "completed",
    }


def test_database_cli_gets_path_only_from_environment_and_never_outputs_it(
    tmp_path: Path,
) -> None:
    database = tmp_path / "private-database.db"
    Storage(str(database)).connect().close()
    state_home = tmp_path / "state"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "database"],
        env=_environment(state_home, SUMICORE_DATABASE_PATH=str(database)),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert str(database) not in result.stdout
    assert str(database) not in result.stderr
    assert str(database) not in json.dumps(_journal_record(state_home))
    assert _journal_record(state_home)["kind"] == "database"
    assert _journal_record(state_home)["job"] == "daily"


def test_operation_cli_rejects_unapproved_job_without_writing(tmp_path: Path) -> None:
    state_home = tmp_path / "state"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "operation",
            "invented_job",
            "completed",
            "1",
            "none",
        ],
        env=_environment(state_home),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert not (state_home / "sumicore" / "operational-metrics.jsonl").exists()


def test_database_cli_hides_configuration_errors(tmp_path: Path) -> None:
    state_home = tmp_path / "state"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "database"],
        env=_environment(state_home),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "unable to record operational metric\n"
    assert "Traceback" not in result.stderr
