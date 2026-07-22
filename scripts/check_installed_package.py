#!/usr/bin/env python3
"""Verify the installed wheel from outside the repository source tree."""

from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    prefix = Path(sys.prefix).resolve()
    site_packages = (prefix / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages").resolve()
    with tempfile.TemporaryDirectory(prefix="sumicore-installed-check-") as directory:
        code = """
import importlib.metadata, json
from pathlib import Path
import hedp, sumicore
print(json.dumps({
  "hedp": str(Path(hedp.__file__).resolve()),
  "sumicore": str(Path(sumicore.__file__).resolve()),
  "version": importlib.metadata.version("sumicore"),
}))
"""
        result = subprocess.run(
            [sys.executable, "-I", "-c", code], cwd=directory,
            capture_output=True, text=True, check=True,
        )
    details = json.loads(result.stdout)
    for package in ("hedp", "sumicore"):
        if not Path(details[package]).is_relative_to(site_packages):
            raise RuntimeError(f"{package} is not loaded from the installed wheel")
    if any(site_packages.glob("__editable__*.pth")):
        raise RuntimeError("editable package marker exists")
    distribution = importlib.metadata.distribution("sumicore")
    direct_url = distribution.read_text("direct_url.json")
    if direct_url and json.loads(direct_url).get("dir_info", {}).get("editable"):
        raise RuntimeError("sumicore is installed in editable mode")
    for command in ("hedp", "sumicore"):
        executable = prefix / "bin" / command
        first_line = executable.read_text(encoding="utf-8").splitlines()[0]
        if first_line != f"#!{sys.executable}":
            raise RuntimeError(f"{command} has a stale interpreter path")
        subprocess.run(
            [str(executable), "--help"], cwd="/private/tmp",
            stdout=subprocess.DEVNULL, check=True,
        )
    subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        stdout=subprocess.DEVNULL, check=True,
    )
    print(f"sumicore {details['version']} installed package: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
