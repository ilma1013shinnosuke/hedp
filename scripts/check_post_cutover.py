#!/usr/bin/env python3
"""Evaluate a redacted SumiCore post-cutover snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from hedp.operations.post_cutover import evaluate_post_cutover


def main() -> int:
    parser = argparse.ArgumentParser(description="保存済みの切替後状態を読み取り検査します")
    parser.add_argument("snapshot", type=Path, help="秘密値を含まないJSON状態ファイル")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = evaluate_post_cutover(json.loads(args.snapshot.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"入力エラー: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"判定: {result['status'].upper()}")
        for finding in result["findings"]:
            print(f"[{finding['level'].upper()}] {finding['message']}")
    return 1 if result["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
