#!/usr/bin/env python3
"""Secret-free, pre-execution acceptance check for HESTIA on sanctum."""

from __future__ import annotations

import argparse
import json
import os
import platform
import stat
import subprocess
from pathlib import Path

EXPECTED_CAPABILITY = "fusionsolar.smartlogger.read_only"


def check_acceptance(
    release_root: Path,
    *,
    profile_path: Path | None = None,
    encrypted_path: Path | None = None,
    system: str | None = None,
    run_command=subprocess.run,
) -> dict[str, object]:
    findings: list[dict[str, str]] = []
    detected_system = system or platform.system()
    _add(findings, "linux_validation_host", detected_system == "Linux")

    profile_path = profile_path or release_root / "config/release/hestia-v1.json"
    encrypted_path = encrypted_path or release_root / "secrets/runtime.sops.env"
    _add(findings, "release_profile_present", profile_path.is_file())
    _add(findings, "encrypted_source_present", encrypted_path.is_file())
    _add(findings, "plaintext_env_absent", not (release_root / ".env").exists())

    profile = _load_profile(profile_path)
    _add(
        findings,
        "execution_mode_shadow",
        profile.get("default_execution_mode") == "shadow",
    )
    capabilities = profile.get("production_capabilities")
    capability_ids = (
        [item.get("id") for item in capabilities if isinstance(item, dict)]
        if isinstance(capabilities, list)
        else []
    )
    _add(
        findings,
        "single_read_only_capability",
        capability_ids == [EXPECTED_CAPABILITY],
    )
    _add(
        findings,
        "linux_scope_deferred",
        "Linux" in profile.get("deferred_platform_qualification", []),
    )

    _add(
        findings,
        "encrypted_source_mode_0600",
        _mode_is_0600(encrypted_path),
    )
    _add(
        findings,
        "encrypted_source_has_no_plain_values",
        _dotenv_is_fully_encrypted(encrypted_path),
    )

    persistent, active, cron = _job_counts(run_command)
    _add(findings, "persistent_jobs_zero", persistent == 0)
    _add(findings, "active_jobs_zero", active == 0)
    _add(findings, "cron_jobs_zero", cron == 0)

    failed = [item["check"] for item in findings if item["status"] == "fail"]
    return {
        "schema_version": 1,
        "status": "fail" if failed else "pass",
        "scope": "linux_read_only_validation",
        "failed_checks": failed,
        "findings": findings,
    }


def _add(findings: list[dict[str, str]], check: str, passed: bool) -> None:
    findings.append({"check": check, "status": "pass" if passed else "fail"})


def _load_profile(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _mode_is_0600(path: Path) -> bool:
    try:
        return stat.S_IMODE(path.stat().st_mode) == 0o600
    except OSError:
        return False


def _dotenv_is_fully_encrypted(path: Path) -> bool:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    values = [
        line.split("=", 1)
        for line in lines
        if line and not line.startswith("#") and "=" in line
    ]
    protected = [
        key.startswith("sops_") or value.startswith("ENC[")
        for key, value in values
    ]
    return bool(protected) and all(protected)


def _job_counts(run_command) -> tuple[int | None, int | None, int | None]:
    commands = (
        ["systemctl", "--user", "list-unit-files", "--no-legend", "hestia*"],
        ["systemctl", "--user", "list-units", "--no-legend", "hestia*"],
        ["crontab", "-l"],
    )
    counts: list[int | None] = []
    for command in commands:
        try:
            result = run_command(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
                env={"PATH": os.environ.get("PATH", "")},
            )
        except (OSError, subprocess.SubprocessError):
            counts.append(None)
            continue
        if result.returncode not in {0, 1}:
            counts.append(None)
            continue
        lines = [
            line
            for line in result.stdout.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        counts.append(len(lines))
    return counts[0], counts[1], counts[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--encrypted-source", type=Path)
    arguments = parser.parse_args()
    report = check_acceptance(
        arguments.release_root,
        profile_path=arguments.profile,
        encrypted_path=arguments.encrypted_source,
    )
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
