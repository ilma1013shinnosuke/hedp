#!/usr/bin/env python3
"""Check secret-free host prerequisites for HESTIA recovery drills."""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from typing import Sequence


REQUIRED_TOOLS = {
    "age": ("--version",),
    "age-keygen": ("--version",),
    "sops": ("--version",),
    "restic": ("version",),
}
SUPPORTED_SYSTEMS = {"Darwin", "Linux"}
MINIMUM_PYTHON = (3, 9)


def check_host(
    *,
    system: str | None = None,
    python_version: tuple[int, int] | None = None,
    path_lookup=shutil.which,
    run_command=subprocess.run,
) -> dict[str, object]:
    """Return only public tool/version facts; never inspect secret files."""

    detected_system = system or platform.system()
    detected_python = python_version or sys.version_info[:2]
    findings: list[dict[str, str]] = []
    findings.append(
        {
            "check": "platform",
            "status": "pass" if detected_system in SUPPORTED_SYSTEMS else "fail",
            "value": detected_system if detected_system in SUPPORTED_SYSTEMS else "unsupported",
        }
    )
    findings.append(
        {
            "check": "python",
            "status": "pass" if detected_python >= MINIMUM_PYTHON else "fail",
            "value": f"{detected_python[0]}.{detected_python[1]}",
        }
    )
    for name, arguments in REQUIRED_TOOLS.items():
        executable = path_lookup(name)
        if executable is None:
            findings.append(
                {"check": f"tool:{name}", "status": "fail", "value": "missing"}
            )
            continue
        version = _safe_version(executable, arguments, run_command)
        findings.append(
            {
                "check": f"tool:{name}",
                "status": "pass" if version is not None else "fail",
                "value": version or "unavailable",
            }
        )
    failed = [item["check"] for item in findings if item["status"] == "fail"]
    return {
        "schema_version": 1,
        "status": "fail" if failed else "pass",
        "failed_checks": failed,
        "findings": findings,
    }


def _safe_version(
    executable: str,
    arguments: Sequence[str],
    run_command,
) -> str | None:
    try:
        result = run_command(
            [executable, *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            env={"SOPS_DISABLE_VERSION_CHECK": "1"},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    first_line = (result.stdout or result.stderr).splitlines()
    if not first_line:
        return None
    value = first_line[0].strip()
    if not value or len(value) > 120:
        return None
    return value


def main() -> int:
    report = check_host()
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
