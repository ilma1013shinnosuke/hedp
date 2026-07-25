from __future__ import annotations

import json

from hedp.adapters.switchbot.cli import (
    _print_safe_summary,
    _safe_import_summary,
)


def test_safe_observation_summary_omits_household_values(capsys) -> None:
    private = "private-device-name-location-or-measurement"
    rows = [
        {
            "device_id": private,
            "observed_at_utc": "2026-07-25T01:02:03+00:00",
            "temperature_c": 27.5,
            "source_file": f"/private/{private}.csv",
            "observation_kind": "environment",
            "measurement_status": "good",
        }
    ]

    _print_safe_summary(rows, "observations")

    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["row_count"] == 1
    assert report["device_count"] == 1
    assert report["groups"]["observation_kind"] == {"environment": 1}
    assert private not in output
    assert "2026-07-25T01:02:03" not in output
    assert "27.5" not in output
    assert "/private/" not in output


def test_safe_import_summary_omits_paths_ids_times_and_hashes() -> None:
    private = "private-device-or-file"
    report = _safe_import_summary(
        {
            "files": [
                {
                    "path": f"/private/{private}.csv",
                    "device_id": private,
                    "first_timestamp": "2026-07-25T01:02:03+00:00",
                    "sha256": private * 2,
                    "rows": 10,
                    "invalid_rows": 1,
                    "status": "blocked",
                }
            ],
            "comparisons": [
                {
                    "csv": f"/private/{private}.csv",
                    "xlsx": f"/private/{private}.xlsx",
                    "identical": False,
                }
            ],
            "status": "blocked",
        }
    )

    encoded = json.dumps(report, ensure_ascii=False)
    assert report["file_count"] == 1
    assert report["comparison_failures"] == 1
    assert report["totals"]["rows"] == 10
    assert report["totals"]["invalid_rows"] == 1
    assert private not in encoded
    assert "/private/" not in encoded
    assert "2026-07-25T" not in encoded
