#!/usr/bin/env python3
"""Create a redacted monitoring snapshot from an explicit JSON facts file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hedp.operations.post_cutover import create_post_cutover_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="明示した非秘密情報から監視入力を作成します")
    parser.add_argument("facts", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    facts = json.loads(arguments.facts.read_text(encoding="utf-8"))
    snapshot = create_post_cutover_snapshot(**facts)
    arguments.output.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    arguments.output.chmod(0o600)
    print(f"作成しました: {arguments.output.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
