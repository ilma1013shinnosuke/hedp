from __future__ import annotations

import ast
import importlib
from pathlib import Path
import tomllib


ROOT = Path(__file__).parents[1]
ADAPTERS_ROOT = ROOT / "src" / "hedp" / "adapters"
OS_SPECIFIC_IMPORTS = frozenset(
    {
        "AppKit",
        "Cocoa",
        "CoreFoundation",
        "Foundation",
        "PyObjCTools",
        "Quartz",
        "Security",
        "fcntl",
        "grp",
        "msvcrt",
        "objc",
        "pty",
        "pwd",
        "resource",
        "syslog",
        "termios",
        "winreg",
    }
)
OS_SPECIFIC_MEMBERS = {
    "os": frozenset(
        {
            "chmod",
            "chown",
            "fchmod",
            "fchown",
            "geteuid",
            "getuid",
            "setgid",
            "setuid",
            "umask",
        }
    ),
    "pathlib": frozenset(
        {
            "PosixPath",
            "PurePosixPath",
            "PureWindowsPath",
            "WindowsPath",
        }
    ),
    "signal": frozenset(
        {
            "SIGALRM",
            "SIGHUP",
            "SIGUSR1",
            "SIGUSR2",
            "pthread_sigmask",
            "setitimer",
        }
    ),
}
OS_SPECIFIC_SOURCE_MARKERS = (
    "launchctl",
    "launchd",
    "osascript",
    "/Users/",
    "/etc/",
    "/home/",
    "/opt/",
    "/tmp/",
    "/var/",
    "C:\\Users\\",
)
ROOT_OPERATION_EXPORTS = {
    "bravia": {
        "BraviaOperation",
        "BraviaDryRunPlanner",
        "BraviaPowerRequest",
    },
    "miele": {
        "MieleCommand",
        "MieleOperationGate",
        "StartScheduledProgramRequest",
    },
    "sakura": {
        "SakuraOperation",
        "SakuraDryRunPlanner",
        "SakuraStartChargingRequest",
    },
    "ecocute": {
        "build_setc_request",
        "EcoCuteOperationAdapter",
        "EcoCuteSetCommand",
    },
}


def _python_files() -> tuple[Path, ...]:
    return tuple(sorted(ADAPTERS_ROOT.rglob("*.py")))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _operation_imports(path: Path) -> tuple[str, ...]:
    found: list[str] = []
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            found.extend(
                alias.name
                for alias in node.names
                if alias.name == "operation" or alias.name.endswith(".operation")
            )
        elif isinstance(node, ast.ImportFrom):
            if node.module == "operation" or (
                node.module is not None and node.module.endswith(".operation")
            ):
                found.append(node.module)
            found.extend(alias.name for alias in node.names if alias.name == "operation")
    return tuple(found)


def _import_roots(path: Path) -> tuple[str, ...]:
    roots: list[str] = []
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            roots.extend(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.append(node.module.split(".", 1)[0])
    return tuple(roots)


def _os_specific_uses(path: Path) -> tuple[str, ...]:
    found: list[str] = []
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.ImportFrom) and node.module in OS_SPECIFIC_MEMBERS:
            found.extend(
                f"{node.module}.{alias.name}"
                for alias in node.names
                if alias.name in OS_SPECIFIC_MEMBERS[node.module]
            )
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in OS_SPECIFIC_MEMBERS
            and node.attr in OS_SPECIFIC_MEMBERS[node.value.id]
        ):
            found.append(f"{node.value.id}.{node.attr}")
    return tuple(found)


def _fixed_os_paths(path: Path) -> tuple[str, ...]:
    return tuple(
        value
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        for value in (node.value,)
        if any(marker in value for marker in OS_SPECIFIC_SOURCE_MARKERS)
    )


def test_non_operation_adapter_modules_never_import_operation_modules() -> None:
    paths = (
        path
        for path in _python_files()
        if path.name != "__init__.py"
        and path.stem != "operation"
    )

    for path in paths:
        assert _operation_imports(path) == (), path


def test_adapter_package_roots_never_import_operation_modules() -> None:
    for path in sorted(ADAPTERS_ROOT.glob("*/__init__.py")):
        assert _operation_imports(path) == (), path


def test_selected_package_roots_export_no_operation_or_set_symbols() -> None:
    for package, forbidden in ROOT_OPERATION_EXPORTS.items():
        module = importlib.import_module(f"hedp.adapters.{package}")
        exported = set(getattr(module, "__all__", ()))

        assert forbidden.isdisjoint(exported), package
        for name in forbidden:
            assert not hasattr(module, name), f"{package}.{name}"


def test_all_adapter_modules_avoid_os_specific_dependencies() -> None:
    for path in _python_files():
        assert OS_SPECIFIC_IMPORTS.isdisjoint(_import_roots(path)), path
        assert _os_specific_uses(path) == (), path
        assert _fixed_os_paths(path) == (), path


def test_windows_declares_tzdata_when_adapters_use_zoneinfo() -> None:
    zoneinfo_users = [
        path for path in _python_files() if "zoneinfo" in _import_roots(path)
    ]
    assert zoneinfo_users

    project = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    dependencies = project["project"]["dependencies"]
    assert any(
        dependency.startswith("tzdata")
        and "platform_system" in dependency
        and "Windows" in dependency
        for dependency in dependencies
    )
