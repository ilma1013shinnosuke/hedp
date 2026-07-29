from __future__ import annotations

import subprocess

import pytest

from scripts.manage_hestia_age_keychain import (
    MAC_RUNTIME_ACCOUNT,
    SERVICE,
    check,
    check_sops,
    delete,
    emit_for_sops,
    probe_sops,
    register,
    sops_age_key_cmd,
)


def _completed(stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


def test_register_uses_security_prompt_without_secret_argument() -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return _completed()

    register(runner)

    command, kwargs = calls[0]
    assert command[-1] == "-w"
    assert SERVICE in command
    assert MAC_RUNTIME_ACCOUNT in command
    assert "AGE-SECRET-KEY-" not in repr(command)
    assert "input" not in kwargs


def test_check_validates_without_printing_identity(capsys: pytest.CaptureFixture[str]) -> None:
    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return _completed("AGE-SECRET-KEY-1ABC234\n")

    check(runner)
    assert capsys.readouterr().out == ""


def test_check_rejects_non_age_value() -> None:
    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return _completed("not-an-age-key\n")

    with pytest.raises(RuntimeError, match="not a valid age identity"):
        check(runner)


def test_emit_for_sops_refuses_interactive_terminal() -> None:
    with pytest.raises(RuntimeError, match="refusing"):
        emit_for_sops(stdout_is_tty=True)


def test_emit_for_sops_allows_pipe(capsys: pytest.CaptureFixture[str]) -> None:
    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return _completed("AGE-SECRET-KEY-1ABC234\n")

    emit_for_sops(runner, stdout_is_tty=False)
    assert capsys.readouterr().out == "AGE-SECRET-KEY-1ABC234\n"


def test_delete_targets_only_stable_service_and_account() -> None:
    calls: list[list[str]] = []

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return _completed()

    delete(runner)
    assert SERVICE in calls[0]
    assert MAC_RUNTIME_ACCOUNT in calls[0]


def test_sops_command_contains_no_identity() -> None:
    command = sops_age_key_cmd("scripts/manage_hestia_age_keychain.py")
    assert command.endswith("manage_hestia_age_keychain.py emit-for-sops")
    assert "AGE-SECRET-KEY-" not in command


def test_sops_check_discards_plaintext_and_passes_only_command(
    tmp_path,
) -> None:
    encrypted = tmp_path / "runtime.sops.env"
    encrypted.write_text("encrypted fixture", encoding="utf-8")
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return _completed()

    check_sops(encrypted, runner, script_path="scripts/manage_hestia_age_keychain.py")

    command, kwargs = calls[0]
    assert command[0].endswith("sops")
    assert command[1:4] == ["decrypt", "--output", "/dev/null"]
    assert kwargs["stdout"] is subprocess.DEVNULL
    environment = kwargs["env"]
    assert isinstance(environment, dict)
    assert environment["SOPS_AGE_KEY_CMD"].endswith(
        "manage_hestia_age_keychain.py emit-for-sops"
    )
    assert "AGE-SECRET-KEY-" not in repr(environment)


def test_probe_uses_only_public_recipient_and_non_secret_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        if "--output" in command:
            from pathlib import Path

            Path(command[command.index("--output") + 1]).write_text(
                "encrypted", encoding="utf-8"
            )
        return _completed("AGE-SECRET-KEY-1ABC234\n")

    monkeypatch.setattr(
        "scripts.manage_hestia_age_keychain.shutil.which",
        lambda name: "/test/sops",
    )
    probe_sops(
        "age1publicrecipient",
        runner,
        script_path="scripts/manage_hestia_age_keychain.py",
    )

    assert calls[0][1]["input"] == '{"probe":"non-secret"}'
    assert "secrets/probe.sops.json" in calls[0][0]
    assert "AGE-SECRET-KEY-" not in repr(calls[0])
