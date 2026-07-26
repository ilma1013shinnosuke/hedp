"""Environment names for constructing the read-only Miele adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
import os

from hedp.environment import require_compatible_environment


@dataclass(frozen=True)
class MieleConfiguration:
    devices_url: str
    events_url: str
    access_token: str = field(repr=False)
    source_device_id: str = field(repr=False)
    target_ref: str = "laundry-appliance"
    rest_timeout_seconds: float = 15.0
    sse_timeout_seconds: float = 30.0
    maximum_events: int = 64

    @classmethod
    def from_environment(cls) -> "MieleConfiguration":
        required = {
            "devices_url": "MIELE_DEVICES_URL",
            "events_url": "MIELE_EVENTS_URL",
            "access_token": "MIELE_ACCESS_TOKEN",
            "source_device_id": "MIELE_DEVICE_ID",
        }
        values = {
            field_name: require_compatible_environment(suffix).strip()
            for field_name, suffix in required.items()
        }
        optional = {
            name: os.environ.get(
                f"SUMICORE_MIELE_{name}",
                os.environ.get(f"HEDP_MIELE_{name}", default),
            )
            for name, default in {
                "TARGET_REF": "laundry-appliance",
                "REST_TIMEOUT_SECONDS": "15",
                "SSE_TIMEOUT_SECONDS": "30",
                "MAXIMUM_EVENTS": "64",
            }.items()
        }
        try:
            rest_timeout = float(optional["REST_TIMEOUT_SECONDS"])
            sse_timeout = float(optional["SSE_TIMEOUT_SECONDS"])
            maximum_events = int(optional["MAXIMUM_EVENTS"])
        except ValueError as error:
            raise RuntimeError("Miele numeric settings are invalid") from error
        if not 0 < rest_timeout <= 120:
            raise RuntimeError("Miele REST timeout is out of range")
        if not 0 < sse_timeout <= 300:
            raise RuntimeError("Miele SSE timeout is out of range")
        if not 1 <= maximum_events <= 1_024:
            raise RuntimeError("Miele maximum events is out of range")
        target_ref = optional["TARGET_REF"].strip()
        if not target_ref:
            raise RuntimeError("Miele target ref must not be empty")
        return cls(
            **values,
            target_ref=target_ref,
            rest_timeout_seconds=rest_timeout,
            sse_timeout_seconds=sse_timeout,
            maximum_events=maximum_events,
        )
