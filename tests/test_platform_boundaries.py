from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SOURCE_ROOT = ROOT / "src" / "hedp"
PORTABLE_DIRECTORIES = ("adapters", "events", "intelligence", "storage")
PORTABLE_CORE_MODULES = (
    "application.py",
    "configuration.py",
    "daily_health.py",
    "environment.py",
    "observations.py",
)
OS_SPECIFIC_IMPORTS = frozenset(
    {
        "AppKit",
        "Cocoa",
        "CoreFoundation",
        "Foundation",
        "PyObjCTools",
        "Quartz",
        "Security",
        "objc",
        "winreg",
    }
)
OS_RUNTIME_MARKERS = (
    "launchctl",
    "launchd",
    "osascript",
    "keychain",
    "/Users/",
    "/Library/LaunchAgents",
    "/System/Library",
    "C:\\Users\\",
)


@pytest.fixture
def anonymous_platform_ports() -> dict[str, str]:
    """A fixture-only contract; it contains no machine or household values."""
    return {
        "service": "scheduler_port",
        "scheduler": "service_port",
        "secret_injection": "environment_provider",
    }


def _portable_python_files() -> tuple[Path, ...]:
    directory_files = (
        path
        for directory in PORTABLE_DIRECTORIES
        for path in (SOURCE_ROOT / directory).rglob("*.py")
    )
    core_files = (SOURCE_ROOT / name for name in PORTABLE_CORE_MODULES)
    return tuple(sorted((*directory_files, *core_files)))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _import_roots(tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def _runtime_literals(tree: ast.Module) -> Iterable[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value.casefold()


def test_portable_core_and_adapters_do_not_import_os_specific_sdks() -> None:
    for path in _portable_python_files():
        assert OS_SPECIFIC_IMPORTS.isdisjoint(_import_roots(_tree(path))), path


def test_portable_core_and_adapters_do_not_embed_macos_runtime_paths_or_tools() -> None:
    for path in _portable_python_files():
        literals = tuple(_runtime_literals(_tree(path)))
        assert not any(
            marker.casefold() in literal
            for marker in OS_RUNTIME_MARKERS
            for literal in literals
        ), path


def test_platform_ports_are_anonymous_and_not_imported_by_portable_scope(
    anonymous_platform_ports: dict[str, str],
) -> None:
    assert set(anonymous_platform_ports) == {
        "service",
        "scheduler",
        "secret_injection",
    }
    forbidden_port_names = set(anonymous_platform_ports.values())
    for path in _portable_python_files():
        imports = _import_roots(_tree(path))
        assert forbidden_port_names.isdisjoint(imports), path


def test_environment_variable_names_are_not_a_platform_secret_backend() -> None:
    environment_source = (SOURCE_ROOT / "environment.py").read_text(encoding="utf-8")
    assert "os.environ" in environment_source
    assert "Keychain" not in environment_source
    assert "Security" not in environment_source
