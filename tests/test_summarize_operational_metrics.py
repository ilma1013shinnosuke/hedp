from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "summarize_operational_metrics.py"


def test_summary_cli_returns_safe_empty_report(tmp_path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--state-home", str(tmp_path / "state")],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert report == {
        "accepted_records": 0,
        "database_capacity": {
            "database_bytes_delta": None,
            "first_database_bytes": None,
            "last_database_bytes": None,
            "observed_days": 0,
        },
        "files_read": 0,
        "invalid_lines": 0,
        "operation_counts": [],
        "operator_counts": [],
        "schema_version": 1,
    }
