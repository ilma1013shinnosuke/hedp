"""Operator-only entry point for an authorized Strip Light 3 fast path.

This diagnostic CLI deliberately bypasses the common ExecutionGate.  HESTIA
UI and automation code must use ``FastLightExecutionPort`` through the common
``ExecutionCoordinator`` instead of importing or launching this module.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence

from .fast_light import FastLightCommand, StripLight3FastCommandTransport


def run(
    arguments: Sequence[str],
    *,
    environment: Mapping[str, str] = os.environ,
) -> dict[str, object]:
    parser = argparse.ArgumentParser(
        description=(
            "Operator-only direct Strip Light 3 command; "
            "not a HESTIA UI/automation entry point"
        )
    )
    parser.add_argument(
        "command",
        choices=("on", "off", "brightness", "temperature", "color"),
    )
    parser.add_argument("parameter", nargs="?")
    parsed = parser.parse_args(list(arguments))

    token = environment.get("SWITCHBOT_TOKEN", "").strip()
    secret = environment.get("SWITCHBOT_SECRET", "").strip()
    device_id = environment.get("SWITCHBOT_STRIP_LIGHT_3_DEVICE_ID", "").strip()
    if not token or not secret or not device_id:
        raise RuntimeError("SwitchBot Strip Light 3 fast-path environment is incomplete")

    command, parameter = _command_and_parameter(parsed.command, parsed.parameter)
    receipt = StripLight3FastCommandTransport(token, secret, device_id).send(
        command,
        parameter,
    )
    return receipt.safe_summary()


def _command_and_parameter(
    command: str,
    parameter: str | None,
) -> tuple[FastLightCommand, str]:
    mapped = {
        "on": FastLightCommand.TURN_ON,
        "off": FastLightCommand.TURN_OFF,
        "brightness": FastLightCommand.SET_BRIGHTNESS,
        "temperature": FastLightCommand.SET_COLOR_TEMPERATURE,
        "color": FastLightCommand.SET_COLOR,
    }[command]
    if mapped in {FastLightCommand.TURN_ON, FastLightCommand.TURN_OFF}:
        if parameter is not None:
            raise ValueError("power commands do not accept a parameter")
        return mapped, "default"
    if parameter is None:
        raise ValueError(f"{command} requires a parameter")
    return mapped, parameter


def main(arguments: Sequence[str] | None = None) -> int:
    import sys

    summary = run(sys.argv[1:] if arguments is None else arguments)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
