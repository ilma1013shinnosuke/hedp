#!/usr/bin/env python3
"""Replace only SwitchBot credentials in a private .env file.

Values are read with hidden terminal input and are never printed.  The update
is atomic, keeps unrelated settings unchanged, and leaves no secret-bearing
backup or temporary file behind.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import stat
import tempfile
from pathlib import Path


_TOKEN = re.compile(r"^[A-Za-z0-9]{96}$")
_SECRET = re.compile(r"^[A-Za-z0-9]{32}$")
_ASSIGNMENT = re.compile(
    r"^(?P<prefix>\s*(?:export\s+)?)"
    r"(?P<name>SWITCHBOT_TOKEN|SWITCHBOT_SECRET)"
    r"(?P<separator>\s*=\s*).*$"
)


def update_env(path: Path, *, token: str, secret: str) -> None:
    """Atomically replace the two credential assignments."""

    _validate_credentials(token=token, secret=secret)
    path = path.resolve()
    original = path.read_text(encoding="utf-8")
    values = {
        "SWITCHBOT_TOKEN": token,
        "SWITCHBOT_SECRET": secret,
    }
    seen: set[str] = set()
    updated_lines: list[str] = []
    for line in original.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        ending = line[len(body) :]
        match = _ASSIGNMENT.match(body)
        if match is None:
            updated_lines.append(line)
            continue
        name = match.group("name")
        if name in seen:
            raise ValueError(f"{name} appears more than once")
        seen.add(name)
        updated_lines.append(
            f"{match.group('prefix')}{name}{match.group('separator')}"
            f"{values[name]}{ending}"
        )
    missing = set(values) - seen
    if missing:
        suffix = "" if original.endswith(("\n", "\r")) or not original else "\n"
        updated_lines.append(suffix)
        for name in sorted(missing):
            updated_lines.append(f"{name}={values[name]}\n")

    file_mode = stat.S_IMODE(path.stat().st_mode)
    if file_mode != 0o600:
        raise PermissionError(".env must have mode 0600 before credentials are changed")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.switchbot-",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write("".join(updated_lines))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _validate_credentials(*, token: str, secret: str) -> None:
    if _TOKEN.fullmatch(token) is None:
        raise ValueError("Token must be exactly 96 letters or digits")
    if _SECRET.fullmatch(secret) is None:
        raise ValueError("Secret must be exactly 32 letters or digits")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely replace SwitchBot Token and Secret in .env"
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".env",
    )
    arguments = parser.parse_args()
    token = getpass.getpass("SwitchBot Token (input hidden): ").strip()
    secret = getpass.getpass("SwitchBot Secret (input hidden): ").strip()
    update_env(arguments.env_file, token=token, secret=secret)
    print("SwitchBot credentials updated safely; values were not displayed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
