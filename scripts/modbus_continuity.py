#!/usr/bin/env python3
"""Prepare a private, opaque continuity identifier for one Modbus collection.

The state is deliberately separate from the production database and the
anonymous operational journal.  It stores only the previous scheduler wall
clock and a one-way boot marker so a later collection can be marked as being
after a reboot or a scheduling gap.  Neither value is printed, logged, sent to
the device, or copied into a RawData payload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
import secrets


_REASONS = {
    "initial",
    "continuous",
    "boot_changed",
    "scheduling_gap",
    "boot_evidence_unavailable",
    "boot_evidence_recovered",
}


def _state_path() -> Path:
    configured = os.environ.get("SUMICORE_MODBUS_CONTINUITY_STATE_PATH")
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            raise ValueError("continuity state path must be absolute")
        return path
    state_home = os.environ.get("XDG_STATE_HOME")
    root = Path(state_home).expanduser() if state_home else Path.home() / ".local" / "state"
    if not root.is_absolute():
        raise ValueError("state home must be absolute")
    return root / "sumicore" / "modbus-continuity.json"


def _require_private_directory(directory: Path) -> None:
    if directory.exists() or directory.is_symlink():
        metadata = os.lstat(directory)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeError("continuity state directory is unsafe")
    else:
        directory.mkdir(parents=True, mode=0o700)
    os.chmod(directory, 0o700)


def _load(path: Path) -> dict[str, object]:
    if not path.exists() and not path.is_symlink():
        return {}
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError("continuity state file is unsafe")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("continuity state is invalid")
    return data


def _boot_marker() -> str | None:
    """Return an opaque boot marker without retaining a machine identifier."""
    try:
        result = subprocess.run(
            ["sysctl", "-n", "kern.boottime"],
            check=True,
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write(path: Path, state: dict[str, object]) -> None:
    encoded = json.dumps(state, separators=(",", ":"), sort_keys=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(*, interval_seconds: int, gap_multiplier: int) -> tuple[str, str]:
    if interval_seconds < 1:
        raise ValueError("interval_seconds must be positive")
    if gap_multiplier < 2:
        raise ValueError("gap_multiplier must be at least two")
    path = _state_path()
    _require_private_directory(path.parent)
    previous = _load(path)
    now = time.time()
    boot_marker = _boot_marker()
    previous_id = previous.get("continuity_id")
    continuity_id = previous_id if isinstance(previous_id, str) and len(previous_id) == 32 else secrets.token_hex(16)
    reason = "initial" if not previous else "continuous"
    previous_boot = previous.get("boot_marker")
    previous_observed = previous.get("observed_at")
    if boot_marker is None:
        # A missing boot marker must break qualification rather than silently
        # treating a reboot as continuous.  It is safe to keep collecting, but
        # the next proven continuity identifier starts only after evidence recovers.
        continuity_id = secrets.token_hex(16)
        reason = "boot_evidence_unavailable"
    elif previous and not isinstance(previous_boot, str):
        continuity_id = secrets.token_hex(16)
        reason = "boot_evidence_recovered"
    elif previous and boot_marker != previous_boot:
        continuity_id = secrets.token_hex(16)
        reason = "boot_changed"
    elif previous and isinstance(previous_observed, (int, float)) and now - previous_observed > interval_seconds * gap_multiplier:
        continuity_id = secrets.token_hex(16)
        reason = "scheduling_gap"
    state = {"continuity_id": continuity_id, "observed_at": now}
    if boot_marker:
        state["boot_marker"] = boot_marker
    _write(path, state)
    return continuity_id, reason


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--gap-multiplier", type=int, default=2)
    arguments = parser.parse_args(argv)
    continuity_id, reason = prepare(
        interval_seconds=arguments.interval_seconds,
        gap_multiplier=arguments.gap_multiplier,
    )
    if reason not in _REASONS:  # Defensive fixed-vocabulary guarantee.
        raise RuntimeError("invalid continuity reason")
    print(f"{continuity_id} {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
