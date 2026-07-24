#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import shlex
import stat
import sys
from pathlib import Path


ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_env_file(path: str | Path) -> dict[str, str]:
    env_path = Path(path)
    mode = stat.S_IMODE(env_path.stat().st_mode)
    if mode & 0o077:
        raise PermissionError("environment file must not be accessible by others")
    values: dict[str, str] = {}
    for line_number, original in enumerate(
        env_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = original.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        if "=" not in line:
            raise ValueError(f"invalid environment line {line_number}")
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not ENVIRONMENT_NAME.fullmatch(name):
            raise ValueError(f"invalid environment name at line {line_number}")
        if value[:1] in {"'", '"'}:
            try:
                parts = shlex.split(value, posix=True)
            except ValueError as error:
                raise ValueError(
                    f"invalid quoted value at line {line_number}"
                ) from error
            if len(parts) != 1:
                raise ValueError(
                    f"quoted value must be one token at line {line_number}"
                )
            value = parts[0]
        values[name] = value
    return values


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if "--" not in arguments:
        raise SystemExit("usage: run_with_env.py ENV_FILE -- COMMAND [ARG ...]")
    separator = arguments.index("--")
    if separator != 1 or len(arguments) < 3:
        raise SystemExit("usage: run_with_env.py ENV_FILE -- COMMAND [ARG ...]")
    environment = {**os.environ, **parse_env_file(arguments[0])}
    command = arguments[2:]
    os.execvpe(command[0], command, environment)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
