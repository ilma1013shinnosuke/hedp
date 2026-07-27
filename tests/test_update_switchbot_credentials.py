from pathlib import Path

import pytest

from scripts.update_switchbot_credentials import update_env


TOKEN = "T" * 96
SECRET = "S" * 32


def private_env(tmp_path: Path, content: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return path


def test_update_env_replaces_only_switchbot_values(tmp_path):
    path = private_env(
        tmp_path,
        "# keep this\n"
        "OTHER_SETTING=unchanged\n"
        "SWITCHBOT_TOKEN='old-token'\n"
        "export SWITCHBOT_SECRET = old-secret\n",
    )

    update_env(path, token=TOKEN, secret=SECRET)

    assert path.read_text(encoding="utf-8") == (
        "# keep this\n"
        "OTHER_SETTING=unchanged\n"
        f"SWITCHBOT_TOKEN={TOKEN}\n"
        f"export SWITCHBOT_SECRET = {SECRET}\n"
    )
    assert path.stat().st_mode & 0o777 == 0o600


def test_update_env_adds_missing_assignments(tmp_path):
    path = private_env(tmp_path, "OTHER_SETTING=unchanged\n")

    update_env(path, token=TOKEN, secret=SECRET)

    content = path.read_text(encoding="utf-8")
    assert "OTHER_SETTING=unchanged\n" in content
    assert f"SWITCHBOT_TOKEN={TOKEN}\n" in content
    assert f"SWITCHBOT_SECRET={SECRET}\n" in content


@pytest.mark.parametrize(
    ("token", "secret"),
    [
        ("short", SECRET),
        (TOKEN, "short"),
        ("!" * 96, SECRET),
        (TOKEN, "!" * 32),
    ],
)
def test_update_env_rejects_invalid_values_without_changing_file(
    tmp_path,
    token,
    secret,
):
    path = private_env(
        tmp_path,
        "SWITCHBOT_TOKEN=old\nSWITCHBOT_SECRET=old\n",
    )
    before = path.read_bytes()

    with pytest.raises(ValueError):
        update_env(path, token=token, secret=secret)

    assert path.read_bytes() == before


def test_update_env_refuses_non_private_file(tmp_path):
    path = private_env(
        tmp_path,
        "SWITCHBOT_TOKEN=old\nSWITCHBOT_SECRET=old\n",
    )
    path.chmod(0o644)

    with pytest.raises(PermissionError, match="0600"):
        update_env(path, token=TOKEN, secret=SECRET)
