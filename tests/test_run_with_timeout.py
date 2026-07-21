from pathlib import Path
import subprocess
import sys


RUNNER = Path(__file__).parents[1] / "scripts" / "run_with_timeout.py"


def test_timeout_runner_returns_child_status() -> None:
    result = subprocess.run(
        [sys.executable, str(RUNNER), "2", sys.executable, "-c", "raise SystemExit(7)"],
        check=False,
    )
    assert result.returncode == 7


def test_timeout_runner_terminates_stopped_command() -> None:
    result = subprocess.run(
        [sys.executable, str(RUNNER), "0.05", sys.executable, "-c", "import time; time.sleep(5)"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 124
    assert "timed out" in result.stderr
