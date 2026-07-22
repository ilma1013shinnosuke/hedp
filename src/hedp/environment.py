from __future__ import annotations

import os


def compatible_environment_names(suffix: str) -> tuple[str, str]:
    return f"SUMICORE_{suffix}", f"HEDP_{suffix}"


def get_compatible_environment(suffix: str, default: str = "") -> str:
    """Return the SumiCore value, falling back to the legacy HEDP name."""
    for name in compatible_environment_names(suffix):
        value = os.environ.get(name)
        if value is not None and value.strip():
            return value
    return default


def require_compatible_environment(suffix: str) -> str:
    value = get_compatible_environment(suffix)
    if not value:
        current, legacy = compatible_environment_names(suffix)
        raise RuntimeError(
            f"Missing required environment variable: {current} "
            f"(or legacy {legacy})"
        )
    return value
