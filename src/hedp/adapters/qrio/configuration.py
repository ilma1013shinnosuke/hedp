"""Environment configuration for the read-only Qrio transport."""

from __future__ import annotations

from dataclasses import dataclass, field

from hedp.environment import get_compatible_environment, require_compatible_environment


@dataclass(frozen=True)
class QrioConfiguration:
    status_url_template: str = field(repr=False)
    health_url: str = field(repr=False)
    history_url_template: str = field(repr=False)
    authorization: str = field(repr=False)
    source_lock_id: str = field(repr=False)
    target_ref: str = "entrance-lock"
    timeout_seconds: float = 10.0
    maximum_response_bytes: int = 1024 * 1024

    @classmethod
    def from_environment(cls) -> "QrioConfiguration":
        required = {
            "status_url_template": "QRIO_STATUS_URL_TEMPLATE",
            "health_url": "QRIO_HEALTH_URL",
            "history_url_template": "QRIO_HISTORY_URL_TEMPLATE",
            "authorization": "QRIO_AUTHORIZATION",
            "source_lock_id": "QRIO_LOCK_ID",
        }
        values = {
            field_name: require_compatible_environment(suffix).strip()
            for field_name, suffix in required.items()
        }
        if any(not value for value in values.values()):
            raise RuntimeError("Qrio required settings must not be empty")
        target_ref = get_compatible_environment(
            "QRIO_TARGET_REF", "entrance-lock"
        ).strip()
        try:
            timeout_seconds = float(
                get_compatible_environment("QRIO_TIMEOUT_SECONDS", "10")
            )
            maximum_response_bytes = int(
                get_compatible_environment(
                    "QRIO_MAXIMUM_RESPONSE_BYTES", str(1024 * 1024)
                )
            )
        except ValueError as error:
            raise RuntimeError("Qrio numeric settings are invalid") from error
        if not target_ref:
            raise RuntimeError("Qrio target ref must not be empty")
        if not 0 < timeout_seconds <= 30:
            raise RuntimeError("Qrio timeout is out of range")
        if not 1 <= maximum_response_bytes <= 4 * 1024 * 1024:
            raise RuntimeError("Qrio response byte limit is out of range")
        return cls(
            **values,
            target_ref=target_ref,
            timeout_seconds=timeout_seconds,
            maximum_response_bytes=maximum_response_bytes,
        )
