"""Offline release-assurance checks for HESTIA.

The checker intentionally refuses to infer live qualification from source code,
fixtures, or unit tests.  A capability can enter a household release only when
the release profile contains explicit, redacted qualification evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any


CHECKLIST_PATTERN = re.compile(r"^- \[(?P<state>[x ~-])\] `(?P<gate>[^`]+)`")
ALLOWED_STAGES = {"development", "candidate", "release"}
ALLOWED_EXECUTION_DEFAULTS = {"disabled", "shadow"}
ALLOWED_LIVE_STATES = {"live_qualified", "deployed"}
REQUIRED_READER_QUALIFICATION_STAGES = {"single", "short", "day_24"}


def _finding(level: str, check: str, message: str) -> dict[str, str]:
    return {"level": level, "check": check, "message": message}


def _report(findings: list[dict[str, str]]) -> dict[str, Any]:
    failed = sum(item["level"] == "fail" for item in findings)
    warned = sum(item["level"] == "warn" for item in findings)
    blockers = [
        item["check"] for item in findings if item["level"] == "fail"
    ]
    return {
        "status": "fail" if failed else "warn" if warned else "pass",
        "release_ready": failed == 0,
        "summary": {
            "pass": len(findings) - failed - warned,
            "warn": warned,
            "fail": failed,
        },
        "blockers": blockers,
        "findings": findings,
    }


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}を読み取れません") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label}はobjectである必要があります")
    return value


def parse_release_checklist(path: Path) -> dict[str, str]:
    """Return gate states without copying evidence text into the report."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError("リリース・チェックシートを読み取れません") from exc
    states: dict[str, str] = {}
    for line in lines:
        match = CHECKLIST_PATTERN.match(line)
        if match:
            states[match.group("gate")] = match.group("state")
    if not states:
        raise ValueError("リリースGateを検出できません")
    return states


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ValueError(f"{field}は空でない文字列の配列である必要があります")
    return value


def _check_reader_qualification_manifest(
    repo: Path,
    capability_id: str,
    relative_path: object,
) -> tuple[bool, str]:
    if not isinstance(relative_path, str) or not relative_path:
        return False, "実機適格性manifestが指定されていません"
    manifest_path = repo / relative_path
    if not manifest_path.is_file():
        return False, "実機適格性manifestが存在しません"
    try:
        manifest = _load_json_object(
            manifest_path, "実機適格性manifest"
        )
    except ValueError:
        return False, "実機適格性manifestを検証できません"
    if manifest.get("schema_version") != 1:
        return False, "実機適格性manifestの形式が未対応です"
    if manifest.get("capability_id") != capability_id:
        return False, "実機適格性manifestの能力IDが一致しません"
    if manifest.get("redacted") is not True:
        return False, "実機適格性manifestが匿名化済みではありません"
    if manifest.get("read_only") is not True:
        return False, "実機適格性試験がread-onlyではありません"
    if manifest.get("settings_changed") is not False:
        return False, "実機適格性試験で設定不変を確認できません"
    if manifest.get("secrets_present") is not False:
        return False, "実機適格性証拠の秘密情報不在を確認できません"
    if manifest.get("device_impact_observed") is not False:
        return False, "実機への悪影響なしを確認できません"
    stages = manifest.get("stages")
    if not isinstance(stages, list):
        return False, "実機適格性試験の段階記録がありません"
    passed_stages = {
        item.get("name")
        for item in stages
        if isinstance(item, dict)
        and item.get("result") == "pass"
        and isinstance(item.get("started_at"), str)
        and bool(item.get("started_at"))
        and isinstance(item.get("ended_at"), str)
        and bool(item.get("ended_at"))
        and isinstance(item.get("sample_count"), int)
        and item.get("sample_count", 0) > 0
    }
    if REQUIRED_READER_QUALIFICATION_STAGES - passed_stages:
        return False, "単発・短時間・24時間の合格証拠が揃っていません"
    summary_sha256 = manifest.get("summary_sha256")
    if not isinstance(summary_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", summary_sha256
    ):
        return False, "匿名集計結果のSHA-256がありません"
    return True, "構造化された実機適格性証拠を確認しました"


def check_hestia_release_assurance(
    repo: Path,
    profile_path: Path | None = None,
) -> dict[str, Any]:
    """Evaluate a release profile using only repository-local, redacted facts."""
    profile_path = profile_path or repo / "config/release/hestia-v1.json"
    profile = _load_json_object(profile_path, "リリースprofile")
    checklist_relative = profile.get(
        "checklist", "docs/release/hestia-v1-checklist.md"
    )
    if not isinstance(checklist_relative, str) or not checklist_relative:
        raise ValueError("checklistは相対pathである必要があります")
    checklist_path = repo / checklist_relative
    states = parse_release_checklist(checklist_path)
    findings: list[dict[str, str]] = []

    schema_version = profile.get("schema_version")
    findings.append(
        _finding(
            "pass" if schema_version == 1 else "fail",
            "profile_schema",
            "リリースprofile形式を確認しました"
            if schema_version == 1
            else "未対応のリリースprofile形式です",
        )
    )

    stage = profile.get("stage")
    findings.append(
        _finding(
            "pass" if stage in ALLOWED_STAGES else "fail",
            "release_stage",
            f"リリース段階は{stage}です"
            if stage in ALLOWED_STAGES
            else "リリース段階が不正です",
        )
    )

    execution_default = profile.get("default_execution_mode")
    findings.append(
        _finding(
            "pass"
            if execution_default in ALLOWED_EXECUTION_DEFAULTS
            else "fail",
            "safe_execution_default",
            "未認定操作は外部送信されません"
            if execution_default in ALLOWED_EXECUTION_DEFAULTS
            else "未認定操作の安全な既定値がありません",
        )
    )

    scope_approved = profile.get("scope_approved")
    findings.append(
        _finding(
            "pass" if scope_approved is True else "fail",
            "scope_approval",
            "保証対象範囲は承認済みです"
            if scope_approved is True
            else "保証対象範囲が未承認です",
        )
    )

    required_documents = _string_list(
        profile.get("required_documents"), "required_documents"
    )
    missing_documents = [
        relative for relative in required_documents if not (repo / relative).is_file()
    ]
    findings.append(
        _finding(
            "fail" if missing_documents else "pass",
            "required_documents",
            "必須運用文書が不足しています"
            if missing_documents
            else "必須運用文書が揃っています",
        )
    )

    required_gates = _string_list(
        profile.get("required_gates"), "required_gates"
    )
    unknown_gates = [gate for gate in required_gates if gate not in states]
    if unknown_gates:
        findings.append(
            _finding(
                "fail",
                "unknown_required_gates",
                "profileに存在しない必須Gateがあります",
            )
        )
    for gate in required_gates:
        state = states.get(gate)
        findings.append(
            _finding(
                "pass" if state == "x" else "fail",
                f"gate:{gate}",
                f"{gate}は完了しています"
                if state == "x"
                else f"{gate}は未完了です",
            )
        )

    capabilities = profile.get("production_capabilities")
    if not isinstance(capabilities, list):
        raise ValueError("production_capabilitiesは配列である必要があります")
    minimum_live = profile.get("minimum_live_capabilities", 1)
    if not isinstance(minimum_live, int) or minimum_live < 0:
        raise ValueError("minimum_live_capabilitiesは0以上の整数です")
    findings.append(
        _finding(
            "pass" if len(capabilities) >= minimum_live else "fail",
            "minimum_live_capabilities",
            "最低限の本番能力が選定されています"
            if len(capabilities) >= minimum_live
            else "本番運用する能力がまだ選定されていません",
        )
    )
    seen_capabilities: set[str] = set()
    for index, capability in enumerate(capabilities):
        if not isinstance(capability, dict):
            raise ValueError(
                f"production_capabilities[{index}]はobjectである必要があります"
            )
        capability_id = capability.get("id")
        state = capability.get("qualification")
        evidence = capability.get("evidence")
        manifest = capability.get("qualification_manifest")
        valid_id = (
            isinstance(capability_id, str)
            and bool(capability_id)
            and capability_id not in seen_capabilities
        )
        if valid_id:
            seen_capabilities.add(capability_id)
        findings.append(
            _finding(
                "pass" if valid_id else "fail",
                f"capability:{index}:identity",
                "能力IDを確認しました"
                if valid_id
                else "能力IDがないか重複しています",
            )
        )
        findings.append(
            _finding(
                "pass" if state in ALLOWED_LIVE_STATES else "fail",
                f"capability:{capability_id or index}:qualification",
                "実機適格性を確認しました"
                if state in ALLOWED_LIVE_STATES
                else "実機適格性が確認されていません",
            )
        )
        evidence_ok = (
            isinstance(evidence, list)
            and bool(evidence)
            and all(
                isinstance(relative, str)
                and relative
                and (repo / relative).is_file()
                for relative in evidence
            )
        )
        findings.append(
            _finding(
                "pass" if evidence_ok else "fail",
                f"capability:{capability_id or index}:evidence",
                "匿名化済み適格性証拠を確認しました"
                if evidence_ok
                else "匿名化済み適格性証拠が不足しています",
            )
        )
        manifest_ok, manifest_message = _check_reader_qualification_manifest(
            repo,
            capability_id if isinstance(capability_id, str) else "",
            manifest,
        )
        findings.append(
            _finding(
                "pass" if manifest_ok else "fail",
                f"capability:{capability_id or index}:qualification_manifest",
                manifest_message,
            )
        )

    if stage == "release":
        findings.append(
            _finding(
                "pass" if profile.get("rollback_verified") is True else "fail",
                "rollback_verified",
                "rollbackは検証済みです"
                if profile.get("rollback_verified") is True
                else "rollbackが未検証です",
            )
        )
    return _report(findings)
