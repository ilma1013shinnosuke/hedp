from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import stat
import subprocess
import tempfile
from typing import Any


LEGACY_REVISION = "aa42b58^"
ENV_ASSIGNMENT = re.compile(
    r"^(?P<prefix>\s*(?:export\s+)?)"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*="
)


def git_text(repository: Path, source_file: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), "show", f"{LEGACY_REVISION}:{source_file}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Could not read legacy source: {source_file}")
    return result.stdout


def literal_assignment(source: str, name: str) -> Any:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError(f"Legacy source does not contain {name}")


def switchbot_configuration(repository: Path) -> dict[str, Any]:
    importer = git_text(repository, "src/hedp/adapters/switchbot/importer.py")
    service = git_text(repository, "src/hedp/adapters/switchbot/service.py")
    filename_device_ids = literal_assignment(importer, "DEVICE_BY_FILENAME")
    confirmed_locations = literal_assignment(service, "CONFIRMED_LOCATIONS")
    location_history = [
        {
            "device_id": device_id,
            "location": location,
            "purpose": purpose,
            "valid_from": valid_from,
            "precision": "day",
            "source": "user_confirmed_inventory",
        }
        for device_id, (location, purpose, valid_from) in confirmed_locations.items()
    ]
    name_history: list[dict[str, str]] = []
    function = next(
        node
        for node in ast.walk(ast.parse(service))
        if isinstance(node, ast.FunctionDef)
        and node.name == "_ensure_confirmed_location_history"
    )
    local_values: dict[str, str] = {}
    for statement in function.body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            try:
                value = ast.literal_eval(statement.value)
            except (ValueError, TypeError):
                continue
            if isinstance(value, str):
                local_values[statement.targets[0].id] = value
        if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
            continue
        call = statement.value
        if not isinstance(call.func, ast.Attribute):
            continue
        if call.func.attr not in {"set_location", "set_name_history"}:
            continue
        try:
            arguments = [_resolve_literal(item, local_values) for item in call.args]
            keywords = {
                item.arg: _resolve_literal(item.value, local_values)
                for item in call.keywords
                if item.arg is not None
            }
        except ValueError:
            continue
        if call.func.attr == "set_location":
            item = {
                "device_id": arguments[0],
                "location": arguments[1],
                "purpose": arguments[2],
                "valid_from": arguments[3],
                "precision": keywords.get("precision", "day"),
                "source": keywords.get("source", "local_household_config"),
            }
            for optional in ("valid_to", "notes"):
                if optional in keywords:
                    item[optional] = keywords[optional]
            location_history.append(item)
        else:
            item = {
                "device_id": arguments[0],
                "name": arguments[1],
                "valid_from": arguments[2],
                "source": keywords.get("source", "local_household_config"),
            }
            if "valid_to" in keywords:
                item["valid_to"] = keywords["valid_to"]
            name_history.append(item)
    return {
        "filename_device_ids": filename_device_ids,
        "location_history": _deduplicate(location_history),
        "name_history": _deduplicate(name_history),
    }


def _resolve_literal(node: ast.AST, local_values: dict[str, str]) -> str:
    if isinstance(node, ast.Name) and node.id in local_values:
        return local_values[node.id]
    value = ast.literal_eval(node)
    if not isinstance(value, str):
        raise ValueError("Expected a string")
    return value


def _deduplicate(items: list[dict[str, str]]) -> list[dict[str, str]]:
    result = []
    seen = set()
    for item in items:
        marker = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if marker not in seen:
            seen.add(marker)
            result.append(item)
    return result


def plist_environment(path: Path) -> dict[str, str]:
    with path.open("rb") as stream:
        payload = plistlib.load(stream)
    environment = payload.get("EnvironmentVariables")
    if not isinstance(environment, dict):
        raise RuntimeError(f"Missing EnvironmentVariables in {path.name}")
    return {str(key): str(value) for key, value in environment.items()}


def fusion_solar_environment(repository: Path) -> dict[str, str]:
    launch_agents = Path.home() / "Library" / "LaunchAgents"
    sources = [
        plist_environment(launch_agents / "com.hedp.collect.plist"),
        plist_environment(launch_agents / "com.hedp.device-realtime.plist"),
        plist_environment(launch_agents / "com.hedp.equipment.plist"),
    ]
    legacy_to_current = {
        "HEDP_FUSIONSOLAR_BASE_URL": "SUMICORE_FUSIONSOLAR_BASE_URL",
        "HEDP_FUSIONSOLAR_STATION_DN": "SUMICORE_FUSIONSOLAR_STATION_DN",
        "HEDP_FUSIONSOLAR_USERNAME": "SUMICORE_FUSIONSOLAR_USERNAME",
        "HEDP_FUSIONSOLAR_PASSWORD": "SUMICORE_FUSIONSOLAR_PASSWORD",
        "HEDP_FUSIONSOLAR_DEVICE_DNS": "SUMICORE_FUSIONSOLAR_DEVICE_DNS",
        "HEDP_DATABASE_PATH": "SUMICORE_DATABASE_PATH",
    }
    result: dict[str, str] = {}
    for legacy_name, current_name in legacy_to_current.items():
        values = {source[legacy_name] for source in sources if legacy_name in source}
        if len(values) != 1:
            raise RuntimeError(f"Legacy plist values disagree or are missing: {legacy_name}")
        result[current_name] = values.pop()
    configuration = git_text(repository, "src/hedp/configuration.py")
    result["SUMICORE_FUSIONSOLAR_BATTERY_DN"] = literal_assignment(
        configuration, "CONFIRMED_BATTERY_DEVICE_DN"
    )
    result["SUMICORE_FUSIONSOLAR_BATTERY_SIGIDS"] = literal_assignment(
        configuration, "CONFIRMED_BATTERY_SIGIDS"
    )
    return result


def check_private_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"Private file must be a regular file: {path}")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise RuntimeError(f"Private file permissions must be 0600: {path}")


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent, text=True
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def update_environment_file(path: Path, values: dict[str, str]) -> None:
    check_private_file(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    remaining = dict(values)
    output = []
    for line in lines:
        match = ENV_ASSIGNMENT.match(line)
        if match and match.group("name") in remaining:
            name = match.group("name")
            output.append(f"{match.group('prefix')}{name}={shlex.quote(remaining.pop(name))}")
        else:
            output.append(line)
    if output and output[-1]:
        output.append("")
    for name in sorted(remaining):
        value = remaining[name]
        if "\n" in value or "\r" in value:
            raise RuntimeError(f"Environment value contains a newline: {name}")
        output.append(f"{name}={shlex.quote(value)}")
    atomic_write(path, "\n".join(output) + "\n")


def ensure_local_ignore(repository: Path) -> None:
    git_directory_result = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "--git-dir"],
        capture_output=True,
        text=True,
        check=True,
    )
    git_directory = Path(git_directory_result.stdout.strip())
    if not git_directory.is_absolute():
        git_directory = repository / git_directory
    exclude = git_directory / "info" / "exclude"
    lines = exclude.read_text(encoding="utf-8").splitlines() if exclude.exists() else []
    if "config/local/" not in lines:
        lines.append("config/local/")
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", type=Path)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    repository = arguments.repository.resolve()
    environment_path = repository / ".env"
    household_path = repository / "config" / "local" / "switchbot_household.json"
    check_private_file(environment_path)
    household = switchbot_configuration(repository)
    environment = fusion_solar_environment(repository)
    environment["SUMICORE_SWITCHBOT_HOUSEHOLD_CONFIG_PATH"] = str(household_path)
    if arguments.apply:
        ensure_local_ignore(repository)
        atomic_write(
            household_path,
            json.dumps(household, ensure_ascii=False, indent=2) + "\n",
        )
        update_environment_file(environment_path, environment)
        check_private_file(household_path)
        if subprocess.run(
            ["git", "-C", str(repository), "check-ignore", "-q", str(household_path)],
            check=False,
        ).returncode != 0:
            raise RuntimeError("Local household configuration is not ignored by Git")
    print(
        "Local configuration migration "
        + ("completed" if arguments.apply else "validated")
        + f": filename mappings={len(household['filename_device_ids'])}, "
        + f"location rows={len(household['location_history'])}, "
        + f"name rows={len(household['name_history'])}, "
        + f"environment keys={len(environment)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
