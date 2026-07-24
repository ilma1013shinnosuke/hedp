from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from scripts.run_with_env import parse_env_file


ROOT = Path(__file__).parents[1]


def env_file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(text)
    path.chmod(0o600)
    return path


def test_parse_env_file_without_executing_shell_syntax(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    path = env_file(
        tmp_path,
        "PLAIN=value\n"
        "QUOTED='value with spaces'\n"
        f"MALICIOUS=$(touch {marker})\n",
    )

    values = parse_env_file(path)

    assert values["PLAIN"] == "value"
    assert values["QUOTED"] == "value with spaces"
    assert values["MALICIOUS"].startswith("$(touch ")
    assert not marker.exists()


def test_parse_env_file_rejects_open_permissions(tmp_path: Path) -> None:
    path = env_file(tmp_path, "VALUE=secret\n")
    path.chmod(0o644)

    with pytest.raises(PermissionError):
        parse_env_file(path)


def test_runner_passes_values_without_printing_them(tmp_path: Path) -> None:
    path = env_file(tmp_path, "FIXTURE_SECRET='not for stdout'\n")
    result = subprocess.run(
        [
            str(ROOT / ".venv" / "bin" / "python"),
            str(ROOT / "scripts" / "run_with_env.py"),
            str(path),
            "--",
            str(ROOT / ".venv" / "bin" / "python"),
            "-c",
            (
                "import os; "
                "raise SystemExit(0 if os.environ.get('FIXTURE_SECRET') "
                "== 'not for stdout' else 1)"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
