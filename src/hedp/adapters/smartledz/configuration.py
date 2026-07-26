"""Environment configuration for the read-only Smart LEDZ transport."""

from __future__ import annotations

from dataclasses import dataclass, field

from hedp.environment import get_compatible_environment, require_compatible_environment


@dataclass(frozen=True)
class SmartLedzConfiguration:
    host: str = field(repr=False)
    port: int
    timeout_seconds: float = 5.0

    @classmethod
    def from_environment(cls) -> "SmartLedzConfiguration":
        host = require_compatible_environment("SMARTLEDZ_HOST").strip()
        try:
            port = int(require_compatible_environment("SMARTLEDZ_PORT"))
            timeout_seconds = float(
                get_compatible_environment("SMARTLEDZ_TIMEOUT_SECONDS", "5")
            )
        except ValueError as error:
            raise RuntimeError("Smart LEDZ numeric settings are invalid") from error
        if not host:
            raise RuntimeError("Smart LEDZ host must not be empty")
        if not 1 <= port <= 65_535:
            raise RuntimeError("Smart LEDZ port is out of range")
        if not 0 < timeout_seconds <= 30:
            raise RuntimeError("Smart LEDZ timeout is out of range")
        return cls(host=host, port=port, timeout_seconds=timeout_seconds)
