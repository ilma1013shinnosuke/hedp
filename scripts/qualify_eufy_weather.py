#!/usr/bin/env python3
"""Run one redacted Eufy weather observation from a fixture or RTSP."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from hedp.adapters.eufy_weather import (
    EufyWeatherCollector,
    OpenCvSnapshotReader,
    RgbFrame,
    SnapshotReader,
    load_eufy_weather_configuration,
    qualification_report,
)


class _FixtureSnapshotReader:
    def __init__(self, path: Path) -> None:
        self._path = path

    def read_snapshot(self, *, timeout_seconds: float) -> RgbFrame:
        del timeout_seconds
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            return RgbFrame(
                pixels=tuple(
                    tuple(tuple(pixel) for pixel in row)
                    for row in payload["pixels"]
                ),
                captured_at=payload["captured_at"],
            )
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
            raise ValueError("fixture is invalid") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="画像・URL・秘密値を出力せずEufy屋外観測を1回確認します"
    )
    parser.add_argument("--config", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path)
    source.add_argument("--live-read-only", action="store_true")
    arguments = parser.parse_args(argv)

    configuration = load_eufy_weather_configuration(arguments.config)
    reader: SnapshotReader
    source_mode: str
    if arguments.fixture is not None:
        reader = _FixtureSnapshotReader(arguments.fixture)
        source_mode = "fixture"
    else:
        stream_url = os.environ.get(configuration.stream_url_env)
        if not stream_url:
            raise SystemExit("configured RTSP environment variable is missing")
        reader = OpenCvSnapshotReader(
            stream_url,
            analysis_width=configuration.analysis_width,
        )
        source_mode = "live_read_only"

    collector = EufyWeatherCollector(
        reader,
        target_ref=configuration.target_alias,
        sky_roi=configuration.sky_roi,
        shadow_roi=configuration.shadow_roi,
        calibration=configuration.calibration,
        timeout_seconds=configuration.timeout_seconds,
        maximum_attempts=configuration.maximum_attempts,
        clock=lambda: datetime.now(timezone.utc),
    )
    report = qualification_report(
        collector.collect(),
        target_alias=configuration.target_alias,
        source_mode=source_mode,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"].startswith("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
