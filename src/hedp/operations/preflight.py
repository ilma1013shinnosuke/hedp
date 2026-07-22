"""Read-only readiness checks that never expose configuration values."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
from typing import Any


GAS_FILES = {
    "AuthHealth.gs", "Collectors.gs", "Config.gs", "HttpSession.gs",
    "Queue.gs", "Triggers.gs", "appsscript.json",
}
GAS_SCOPES = {
    "https://www.googleapis.com/auth/script.external_request",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/script.scriptapp",
    "https://www.googleapis.com/auth/script.send_mail",
}
REQUIRED_ENVIRONMENT_SUFFIXES = {
    "DATABASE_PATH", "FUSIONSOLAR_BASE_URL", "FUSIONSOLAR_STATION_DN",
    "FUSIONSOLAR_USERNAME", "FUSIONSOLAR_PASSWORD",
    "FUSIONSOLAR_DEVICE_DNS", "FUSIONSOLAR_BATTERY_DN",
    "FUSIONSOLAR_BATTERY_SIGIDS", "SWITCHBOT_HOUSEHOLD_CONFIG_PATH",
}


def _finding(level: str, check: str, message: str) -> dict[str, str]:
    return {"level": level, "check": check, "message": message}


def _report(findings: list[dict[str, str]]) -> dict[str, Any]:
    failed = sum(item["level"] == "fail" for item in findings)
    warned = sum(item["level"] == "warn" for item in findings)
    return {
        "status": "fail" if failed else "warn" if warned else "pass",
        "summary": {"pass": len(findings) - failed - warned,
                    "warn": warned, "fail": failed},
        "findings": findings,
    }


def check_gas_source(root: Path) -> dict[str, Any]:
    """Validate deployable GAS source without contacting Google or FusionSolar."""
    findings = []
    missing = sorted(name for name in GAS_FILES if not (root / name).is_file())
    findings.append(_finding(
        "fail" if missing else "pass", "required_files",
        "不足ファイル: " + ", ".join(missing) if missing else "必要ファイルが揃っています",
    ))
    try:
        manifest = json.loads((root / "appsscript.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        manifest = {}
    scopes = set(manifest.get("oauthScopes", []))
    findings.append(_finding(
        "pass" if scopes == GAS_SCOPES else "fail", "oauth_scopes",
        "OAuth権限は想定どおりです" if scopes == GAS_SCOPES else "OAuth権限が想定と異なります",
    ))
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in root.glob("*.gs")
    )
    contracts = (
        "SUMICORE_QUEUE_SCHEMA_VERSION = 2", "payload_text: payloadText",
        "SUMICORE_MAX_ATTEMPTS_PER_SOURCE_DATE = 3",
        "LockService.getScriptLock", "SUMICORE_FUSIONSOLAR_MAX_RESPONSE_BYTES",
        "fusionSolarAuthenticationFailureReason_",
    )
    missing_contracts = [value for value in contracts if value not in source]
    findings.append(_finding(
        "fail" if missing_contracts else "pass", "safety_contracts",
        "安全契約が不足しています" if missing_contracts else "安全契約を確認しました",
    ))
    forbidden = ("FUSIONSOLAR_PASSWORD", "FUSIONSOLAR_USERNAME", "NE=")
    findings.append(_finding(
        "fail" if any(value in source for value in forbidden) else "pass",
        "embedded_household_values", "家庭固有値の疑いがあります"
        if any(value in source for value in forbidden) else "家庭固有値は埋め込まれていません",
    ))
    return _report(findings)


def environment_key_names(path: Path) -> set[str]:
    """Return names only; never return or log environment values."""
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            names.add(stripped.split("=", 1)[0].removeprefix("export ").strip())
    return names


def check_cutover_preflight(repo: Path, environment_path: Path) -> dict[str, Any]:
    """Check local prerequisites without opening the DB or touching launchd."""
    findings = []
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True,
        text=True, check=False,
    )
    findings.append(_finding(
        "pass" if status.returncode == 0 and not status.stdout else "fail",
        "git_clean", "Git作業ツリーはcleanです"
        if status.returncode == 0 and not status.stdout else "Git作業ツリーに変更があります",
    ))
    private = environment_path.is_file() and (environment_path.stat().st_mode & 0o777) == 0o600
    findings.append(_finding(
        "pass" if private else "fail", "environment_permissions",
        ".envはmode 0600です" if private else ".envが存在しないかmode 0600ではありません",
    ))
    try:
        names = environment_key_names(environment_path)
    except OSError:
        names = set()
    missing = sorted(
        suffix for suffix in REQUIRED_ENVIRONMENT_SUFFIXES
        if not ({f"SUMICORE_{suffix}", f"HEDP_{suffix}"} & names)
    )
    switchbot_names = {"SWITCHBOT_TOKEN", "SWITCHBOT_SECRET"}
    missing.extend(sorted(switchbot_names - names))
    findings.append(_finding(
        "fail" if missing else "pass", "environment_key_names",
        "不足している設定項目名: " + ", ".join(missing)
        if missing else "必要な設定項目名が揃っています（値は未表示）",
    ))
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", str(environment_path)], cwd=repo,
        check=False,
    ).returncode == 0
    findings.append(_finding(
        "pass" if ignored else "fail", "environment_git_ignored",
        ".envはGit管理外です" if ignored else ".envがGit除外されていません",
    ))
    free = shutil.disk_usage(repo).free
    findings.append(_finding(
        "pass" if free >= 9 * 1024**3 else "warn", "free_space",
        "空き容量は9 GiB以上です" if free >= 9 * 1024**3 else "空き容量が9 GiB未満です",
    ))
    runtime_ok = sys.version_info >= (3, 11) and "LibreSSL" not in ssl.OPENSSL_VERSION
    findings.append(_finding(
        "pass" if runtime_ok else "fail", "python_tls_runtime",
        "Python/TLS実行環境は要件を満たします" if runtime_ok
        else "Python 3.11以上かつOpenSSL実行環境が必要です",
    ))
    return _report(findings)
