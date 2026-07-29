from __future__ import annotations

from dataclasses import dataclass

from scripts.check_sanctum_release_host import check_host


@dataclass
class Result:
    returncode: int = 0
    stdout: str = "tool 1.0\n"
    stderr: str = ""


def test_ready_host_reports_only_public_prerequisite_facts() -> None:
    commands: list[list[str]] = []

    def run(command, **kwargs):
        commands.append(command)
        assert kwargs["timeout"] == 5
        assert kwargs["env"] == {"SOPS_DISABLE_VERSION_CHECK": "1"}
        return Result(stdout=f"{command[0]} 1.0\n")

    report = check_host(
        system="Darwin",
        python_version=(3, 13),
        path_lookup=lambda name: f"/safe/bin/{name}",
        run_command=run,
    )

    assert report["status"] == "pass"
    assert report["failed_checks"] == []
    assert len(commands) == 4
    assert "secret" not in repr(report).lower()
    assert "recipient" not in repr(report).lower()


def test_missing_tool_and_unsupported_platform_fail_closed() -> None:
    report = check_host(
        system="Windows",
        python_version=(3, 8),
        path_lookup=lambda name: None if name == "restic" else f"/bin/{name}",
        run_command=lambda command, **kwargs: Result(),
    )

    assert report["status"] == "fail"
    assert report["failed_checks"] == [
        "platform",
        "python",
        "tool:restic",
    ]


def test_broken_or_oversized_version_output_is_not_forwarded() -> None:
    def run(command, **kwargs):
        if command[0].endswith("age"):
            return Result(returncode=1, stderr="private diagnostic")
        return Result(stdout="x" * 121)

    report = check_host(
        system="Linux",
        python_version=(3, 11),
        path_lookup=lambda name: f"/bin/{name}",
        run_command=run,
    )

    assert report["status"] == "fail"
    assert all(
        item["value"] == "unavailable"
        for item in report["findings"]
        if item["check"].startswith("tool:")
    )
    assert "private diagnostic" not in repr(report)
