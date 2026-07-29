#!/usr/bin/env python3
"""Manage HESTIA's macOS age identity without exposing it in arguments or logs."""

from __future__ import annotations

import argparse
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

SERVICE = "jp.sumicore.hestia.sops-age"
MAC_RUNTIME_ACCOUNT = "runtime.mac.primary.v1"
LABEL = "HESTIA SOPS age runtime identity (Mac)"
AGE_IDENTITY = re.compile(r"^AGE-SECRET-KEY-1[0-9A-Z]+$")

Runner = Callable[..., subprocess.CompletedProcess[str]]


def _security_command(*arguments: str) -> list[str]:
    return ["/usr/bin/security", *arguments]


def register(runner: Runner = subprocess.run) -> None:
    """Prompt inside macOS security; never receive the identity in this process."""
    runner(
        _security_command(
            "add-generic-password",
            "-U",
            "-a",
            MAC_RUNTIME_ACCOUNT,
            "-s",
            SERVICE,
            "-l",
            LABEL,
            "-T",
            "/usr/bin/security",
            "-w",
        ),
        check=True,
        text=True,
    )


def _read_identity(runner: Runner = subprocess.run) -> str:
    result = runner(
        _security_command(
            "find-generic-password",
            "-a",
            MAC_RUNTIME_ACCOUNT,
            "-s",
            SERVICE,
            "-w",
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    identity = result.stdout.strip()
    if not AGE_IDENTITY.fullmatch(identity):
        raise RuntimeError("Keychain item is not a valid age identity")
    return identity


def check(runner: Runner = subprocess.run) -> None:
    _read_identity(runner)


def emit_for_sops(
    runner: Runner = subprocess.run,
    *,
    stdout_is_tty: bool | None = None,
) -> None:
    """Emit only to a consuming process, never to an interactive terminal."""
    is_tty = sys.stdout.isatty() if stdout_is_tty is None else stdout_is_tty
    if is_tty:
        raise RuntimeError("refusing to display an age identity on a terminal")
    sys.stdout.write(_read_identity(runner) + "\n")


def delete(runner: Runner = subprocess.run) -> None:
    runner(
        _security_command(
            "delete-generic-password",
            "-a",
            MAC_RUNTIME_ACCOUNT,
            "-s",
            SERVICE,
        ),
        check=True,
        text=True,
    )


def check_sops(
    encrypted_file: Path,
    runner: Runner = subprocess.run,
    *,
    script_path: str = __file__,
) -> None:
    if not encrypted_file.is_file():
        raise RuntimeError("encrypted SOPS file does not exist")
    sops = shutil.which("sops")
    if sops is None:
        local_sops = Path.home() / ".local" / "bin" / "sops"
        if not local_sops.is_file():
            raise RuntimeError("sops executable was not found")
        sops = str(local_sops)
    environment = os.environ.copy()
    environment["SOPS_AGE_KEY_CMD"] = sops_age_key_cmd(script_path)
    runner(
        [sops, "decrypt", "--output", os.devnull, str(encrypted_file)],
        check=True,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def probe_sops(
    recipient: str,
    runner: Runner = subprocess.run,
    *,
    script_path: str = __file__,
) -> None:
    if not recipient.startswith("age1"):
        raise RuntimeError("public age recipient is invalid")
    sops = shutil.which("sops")
    if sops is None:
        local_sops = Path.home() / ".local" / "bin" / "sops"
        if not local_sops.is_file():
            raise RuntimeError("sops executable was not found")
        sops = str(local_sops)
    with tempfile.TemporaryDirectory(prefix="hestia-sops-probe-") as directory:
        encrypted = Path(directory) / "probe.sops.json"
        runner(
            [
                sops,
                "encrypt",
                "--age",
                recipient,
                "--input-type",
                "json",
                "--output-type",
                "json",
                "--filename-override",
                "secrets/probe.sops.json",
                "--output",
                str(encrypted),
                "/dev/stdin",
            ],
            check=True,
            input='{"probe":"non-secret"}',
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        check_sops(encrypted, runner, script_path=script_path)


def sops_age_key_cmd(script_path: str) -> str:
    absolute = os.path.abspath(script_path)
    return (
        f"{shlex.quote(sys.executable)} {shlex.quote(absolute)} emit-for-sops"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="HESTIA age identityをmacOS Keychainで安全に管理します"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("register", help="Keychain promptから初期登録・更新")
    subparsers.add_parser("check", help="秘密値を表示せず存在と形式を確認")
    subparsers.add_parser(
        "emit-for-sops",
        help="SOPS_AGE_KEY_CMD専用。terminalへの直接表示は拒否",
    )
    sops_parser = subparsers.add_parser(
        "check-sops",
        help="平文を出力せず暗号化fileの復号疎通を確認",
    )
    sops_parser.add_argument("encrypted_file", type=Path)
    probe_parser = subparsers.add_parser(
        "probe-sops",
        help="非秘密probeでKeychainとSOPSの疎通を確認",
    )
    probe_parser.add_argument("--recipient", required=True)
    delete_parser = subparsers.add_parser("delete", help="Keychain項目を削除")
    delete_parser.add_argument(
        "--confirm-service",
        required=True,
        help="削除対象確認のためservice名を正確に指定",
    )
    subparsers.add_parser("print-command", help="SOPS_AGE_KEY_CMD設定値を表示")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if platform.system() != "Darwin":
        print("macOS Keychain is required", file=sys.stderr)
        return 2
    try:
        if arguments.command == "register":
            register()
            print("registered")
        elif arguments.command == "check":
            check()
            print("available")
        elif arguments.command == "emit-for-sops":
            emit_for_sops()
        elif arguments.command == "check-sops":
            check_sops(arguments.encrypted_file)
            print("sops-decryption-available")
        elif arguments.command == "probe-sops":
            probe_sops(arguments.recipient)
            print("sops-keychain-probe-passed")
        elif arguments.command == "delete":
            if arguments.confirm_service != SERVICE:
                raise RuntimeError("service confirmation does not match")
            delete()
            print("deleted")
        else:
            print(sops_age_key_cmd(__file__))
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"failed: {type(error).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
