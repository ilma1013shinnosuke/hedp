import json
from pathlib import Path

import pytest

from hedp.operations.release_assurance import check_hestia_release_assurance


def _write_repo(
    root: Path,
    *,
    scope_approved: bool = True,
    stage: str = "candidate",
    gate_state: str = "x",
    qualification: str = "live_qualified",
) -> Path:
    (root / "docs").mkdir()
    (root / "config").mkdir()
    (root / "docs/checklist.md").write_text(
        f"- [{gate_state}] `R1-01` required gate\n",
        encoding="utf-8",
    )
    (root / "docs/required.md").write_text("required\n", encoding="utf-8")
    (root / "docs/evidence.md").write_text("redacted\n", encoding="utf-8")
    (root / "docs/qualification.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "capability_id": "reader.example",
                "redacted": True,
                "read_only": True,
                "settings_changed": False,
                "secrets_present": False,
                "device_impact_observed": False,
                "summary_sha256": "a" * 64,
                "stages": [
                    {
                        "name": name,
                        "result": "pass",
                        "started_at": "2026-07-28T00:00:00Z",
                        "ended_at": "2026-07-28T00:01:00Z",
                        "sample_count": 1,
                    }
                    for name in ("single", "short", "day_24")
                ],
            }
        ),
        encoding="utf-8",
    )
    profile = {
        "schema_version": 1,
        "release_id": "test",
        "stage": stage,
        "scope_approved": scope_approved,
        "default_execution_mode": "shadow",
        "checklist": "docs/checklist.md",
        "required_documents": ["docs/required.md"],
        "required_gates": ["R1-01"],
        "minimum_live_capabilities": 1,
        "production_capabilities": [
            {
                "id": "reader.example",
                "qualification": qualification,
                "evidence": ["docs/evidence.md"],
                "qualification_manifest": "docs/qualification.json",
            }
        ],
        "rollback_verified": True,
    }
    profile_path = root / "config/profile.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    return profile_path


def test_complete_candidate_profile_passes(tmp_path: Path) -> None:
    profile = _write_repo(tmp_path)
    report = check_hestia_release_assurance(tmp_path, profile)
    assert report["status"] == "pass"
    assert report["release_ready"] is True
    assert report["blockers"] == []


@pytest.mark.parametrize(
    ("field", "kwargs", "expected_blocker"),
    [
        ("scope", {"scope_approved": False}, "scope_approval"),
        ("gate", {"gate_state": " "}, "gate:R1-01"),
        (
            "qualification",
            {"qualification": "fixture_only"},
            "capability:reader.example:qualification",
        ),
    ],
)
def test_unqualified_release_facts_are_blockers(
    tmp_path: Path,
    field: str,
    kwargs: dict[str, object],
    expected_blocker: str,
) -> None:
    del field
    profile = _write_repo(tmp_path, **kwargs)
    report = check_hestia_release_assurance(tmp_path, profile)
    assert report["status"] == "fail"
    assert expected_blocker in report["blockers"]


def test_release_requires_verified_rollback(tmp_path: Path) -> None:
    profile_path = _write_repo(tmp_path, stage="release")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["rollback_verified"] = False
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    report = check_hestia_release_assurance(tmp_path, profile_path)
    assert "rollback_verified" in report["blockers"]


def test_live_capability_requires_complete_structured_evidence(
    tmp_path: Path,
) -> None:
    profile_path = _write_repo(tmp_path)
    manifest_path = tmp_path / "docs/qualification.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["stages"] = manifest["stages"][:2]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = check_hestia_release_assurance(tmp_path, profile_path)
    assert (
        "capability:reader.example:qualification_manifest"
        in report["blockers"]
    )


def test_live_capability_rejects_unredacted_evidence(tmp_path: Path) -> None:
    profile_path = _write_repo(tmp_path)
    manifest_path = tmp_path / "docs/qualification.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["redacted"] = False
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = check_hestia_release_assurance(tmp_path, profile_path)
    assert (
        "capability:reader.example:qualification_manifest"
        in report["blockers"]
    )


def test_current_profile_blocks_premature_household_release() -> None:
    repo = Path(__file__).resolve().parents[1]
    report = check_hestia_release_assurance(repo)
    assert report["status"] == "fail"
    assert "scope_approval" not in report["blockers"]
    assert "minimum_live_capabilities" not in report["blockers"]
    assert "gate:R3-07" not in report["blockers"]


def test_fusionsolar_manifest_is_promoted_only_with_all_stage_evidence() -> None:
    repo = Path(__file__).resolve().parents[1]
    profile = json.loads(
        (repo / "config/release/hestia-v1.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (
            repo
            / "config/release/qualification"
            / "fusionsolar-smartlogger-read-only.json"
        ).read_text(encoding="utf-8")
    )

    assert manifest["capability_id"] == profile["approved_scope"][
        "production_candidate"
    ]
    assert {stage["result"] for stage in manifest["stages"]} == {"pass"}
    assert all(stage["started_at"] and stage["ended_at"] for stage in manifest["stages"])
    assert profile["production_capabilities"] == [
        {
            "id": "fusionsolar.smartlogger.read_only",
            "qualification": "live_qualified",
            "evidence": [
                "docs/release/hestia-v1-fusionsolar-qualification.md"
            ],
            "qualification_manifest": (
                "config/release/qualification/"
                "fusionsolar-smartlogger-read-only.json"
            ),
        }
    ]
