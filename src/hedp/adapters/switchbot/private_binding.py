"""Secret-safe one-time binding helpers for SwitchBot devices."""

from __future__ import annotations

import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any


def resolve_unique_device(payload: dict[str, Any], device_type: str) -> str:
    """Return one private device identifier without logging it."""
    if not device_type:
        raise ValueError("device_type is required")
    body = payload.get("body")
    if not isinstance(body, dict):
        raise ValueError("device list body is invalid")
    devices = body.get("deviceList")
    if not isinstance(devices, list):
        raise ValueError("device list is invalid")
    identifiers = [
        item.get("deviceId")
        for item in devices
        if isinstance(item, dict) and item.get("deviceType") == device_type
    ]
    valid = [value for value in identifiers if isinstance(value, str) and value]
    if len(valid) != 1:
        raise ValueError(f"exactly one {device_type} is required")
    return valid[0]


def update_private_assignment(path: Path, value: str, *, name: str) -> None:
    """Atomically update one mode-0600 environment assignment.

    The runtime Adapter is platform-neutral, but this local installer currently
    relies on POSIX permission semantics.  It fails closed elsewhere instead
    of pretending that ``chmod(0600)`` provides an equivalent Windows ACL.
    """
    if os.name != "posix":
        raise OSError(
            "private binding installer requires a POSIX host; "
            "use a platform credential installer"
        )
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
        raise ValueError("invalid environment variable name")
    if not value or "\n" in value or "\r" in value:
        raise ValueError("invalid private binding")
    assignment = re.compile(
        rf"^(?P<prefix>\s*(?:export\s+)?)({re.escape(name)})"
        rf"(?P<separator>\s*=\s*).*$"
    )
    path = path.resolve()
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise PermissionError(".env must have mode 0600")
    original = path.read_text(encoding="utf-8")
    seen = False
    lines: list[str] = []
    for line in original.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        ending = line[len(body) :]
        match = assignment.match(body)
        if match is None:
            lines.append(line)
            continue
        if seen:
            raise ValueError(f"{name} appears more than once")
        seen = True
        lines.append(
            f"{match.group('prefix')}{name}{match.group('separator')}{value}{ending}"
        )
    if not seen:
        if original and not original.endswith(("\n", "\r")):
            lines.append("\n")
        lines.append(f"{name}={value}\n")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.binding-",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        # The deployment layer handles any stronger platform-specific ACLs.
        temporary_path.chmod(0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write("".join(lines))
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
