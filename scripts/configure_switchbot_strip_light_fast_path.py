#!/usr/bin/env python3
"""Resolve one Strip Light 3 once and store its private binding in .env."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from hedp.adapters.switchbot.client import SwitchBotClient
from hedp.adapters.switchbot.private_binding import (
    resolve_unique_device,
    update_private_assignment,
)


_NAME = "SWITCHBOT_STRIP_LIGHT_3_DEVICE_ID"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".env",
    )
    arguments = parser.parse_args()
    token = os.environ.get("SWITCHBOT_TOKEN", "").strip()
    secret = os.environ.get("SWITCHBOT_SECRET", "").strip()
    if not token or not secret:
        raise RuntimeError("SwitchBot credentials are not loaded")
    payload = SwitchBotClient(
        token,
        secret,
        timeout_seconds=5,
        max_attempts=1,
    ).devices()
    private_binding = resolve_unique_device(payload, "Strip Light 3")
    update_private_assignment(arguments.env_file, private_binding, name=_NAME)
    print(
        "Strip Light 3 fast path configured safely; "
        "private identifier was not displayed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
