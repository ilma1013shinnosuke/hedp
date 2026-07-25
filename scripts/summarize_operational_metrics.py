#!/usr/bin/env python3
"""Print aggregate, anonymous operational-metrics facts as JSON."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPOSITORY_SOURCE = Path(__file__).resolve().parents[1] / "src"
if str(REPOSITORY_SOURCE) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_SOURCE))

from hedp.operations.operational_metrics import summarize_operational_metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-home", type=Path)
    arguments = parser.parse_args(argv)
    try:
        summary = summarize_operational_metrics(arguments.state_home)
    except Exception:
        print("unable to summarize operational metrics", file=sys.stderr)
        return 1
    print(json.dumps(summary, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
