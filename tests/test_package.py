def test_package_import() -> None:
    import hedp
    import sumicore

    assert hedp is not None
    assert sumicore is not None


def test_setup_documentation_uses_regular_install_for_python_313() -> None:
    from pathlib import Path

    root = Path(__file__).parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    runtime = (root / "docs/python-runtime.md").read_text(encoding="utf-8")
    assert "python -m pip install -e ." not in readme
    assert "__editable__" in runtime
    assert "pip install --no-deps ." in runtime
    assert "check_installed_package.py" in runtime
    assert ".venv-next`は絶対pathを持つためrenameしない" in runtime


def test_package_discovery_is_explicit() -> None:
    from pathlib import Path

    project = (Path(__file__).parents[1] / "pyproject.toml").read_text()
    assert 'include = ["hedp*", "sumicore*"]' in project
