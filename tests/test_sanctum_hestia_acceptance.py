from __future__ import annotations

import json
from dataclasses import dataclass

from scripts.check_sanctum_hestia_acceptance import check_acceptance


@dataclass
class Result:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def _release(tmp_path):
    root = tmp_path / "release"
    (root / "config/release").mkdir(parents=True)
    (root / "secrets").mkdir()
    (root / "config/release/hestia-v1.json").write_text(
        json.dumps(
            {
                "default_execution_mode": "shadow",
                "deferred_platform_qualification": ["Linux", "Windows"],
                "production_capabilities": [
                    {"id": "fusionsolar.smartlogger.read_only"}
                ],
            }
        ),
        encoding="utf-8",
    )
    encrypted = root / "secrets/runtime.sops.env"
    encrypted.write_text(
        "TOKEN=ENC[AES256_GCM,data:x]\nsops_age__list_0__map_enc=public\n",
        encoding="utf-8",
    )
    encrypted.chmod(0o600)
    return root


def test_secret_free_acceptance_passes_for_zero_job_linux_release(tmp_path) -> None:
    report = check_acceptance(
        _release(tmp_path),
        system="Linux",
        run_command=lambda command, **kwargs: Result(),
    )

    assert report["status"] == "pass"
    assert report["failed_checks"] == []
    assert "TOKEN" not in repr(report)
    assert "recipient" not in repr(report).lower()


def test_acceptance_fails_closed_for_plaintext_or_existing_jobs(tmp_path) -> None:
    root = _release(tmp_path)
    (root / "secrets/runtime.sops.env").write_text(
        "TOKEN=plaintext\n", encoding="utf-8"
    )

    report = check_acceptance(
        root,
        system="Linux",
        run_command=lambda command, **kwargs: Result(stdout="one\n"),
    )

    assert report["status"] == "fail"
    assert "encrypted_source_has_no_plain_values" in report["failed_checks"]
    assert "persistent_jobs_zero" in report["failed_checks"]
    assert "active_jobs_zero" in report["failed_checks"]
    assert "cron_jobs_zero" in report["failed_checks"]


def test_acceptance_rejects_non_linux_host_and_plaintext_env(tmp_path) -> None:
    root = _release(tmp_path)
    (root / ".env").write_text("not-read", encoding="utf-8")

    report = check_acceptance(
        root,
        system="Darwin",
        run_command=lambda command, **kwargs: Result(),
    )

    assert "linux_validation_host" in report["failed_checks"]
    assert "plaintext_env_absent" in report["failed_checks"]


def test_acceptance_supports_explicit_deployment_layout(tmp_path) -> None:
    root = _release(tmp_path)
    deployed = tmp_path / "app"
    (deployed / "current/source/config/release").mkdir(parents=True)
    (deployed / "secrets").mkdir(parents=True)
    profile = deployed / "current/source/config/release/hestia-v1.json"
    encrypted = deployed / "secrets/runtime.sops.env"
    profile.write_bytes((root / "config/release/hestia-v1.json").read_bytes())
    encrypted.write_bytes((root / "secrets/runtime.sops.env").read_bytes())
    encrypted.chmod(0o600)

    report = check_acceptance(
        deployed / "current",
        profile_path=profile,
        encrypted_path=encrypted,
        system="Linux",
        run_command=lambda command, **kwargs: Result(),
    )

    assert report["status"] == "pass"
