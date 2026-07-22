#!/usr/bin/env python3
"""Run redacted GAS or local-cutover readiness checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hedp.operations.preflight import check_cutover_preflight, check_gas_source


def main() -> int:
    parser = argparse.ArgumentParser(description="秘密値を表示せず配備準備を確認します")
    subparsers = parser.add_subparsers(dest="command", required=True)
    gas = subparsers.add_parser("gas")
    gas.add_argument("path", type=Path)
    cutover = subparsers.add_parser("cutover")
    cutover.add_argument("repo", type=Path)
    cutover.add_argument("--env", type=Path, required=True)
    arguments = parser.parse_args()
    report = (
        check_gas_source(arguments.path)
        if arguments.command == "gas"
        else check_cutover_preflight(arguments.repo, arguments.env)
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
