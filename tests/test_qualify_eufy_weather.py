from __future__ import annotations

import json
from pathlib import Path

from scripts.qualify_eufy_weather import main


ROOT = Path(__file__).parents[1]


def test_fixture_qualification_is_redacted_and_does_not_need_camera(
    capsys,
) -> None:
    result = main(
        [
            "--config",
            str(ROOT / "config" / "examples" / "eufy_weather.example.json"),
            "--fixture",
            str(
                ROOT
                / "tests"
                / "fixtures"
                / "eufy_weather"
                / "direct_sun_anonymous.json"
            ),
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert result == 0
    assert report["status"] == "pass_with_calibration_pending"
    assert report["source_mode"] == "fixture"
    assert report["target_alias"] == "garden_weather_camera"
    assert report["image_retained"] is False
    encoded = json.dumps(report)
    assert "pixels" not in encoded
    assert "rtsp://" not in encoded
