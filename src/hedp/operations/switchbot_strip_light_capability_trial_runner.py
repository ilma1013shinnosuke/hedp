"""Environment-backed entry point for the compensated Strip Light 3 trial."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping

from .switchbot_strip_light_capability_trial import (
    BoundedStripCapabilityCommandTransport,
    MAXIMUM_STATUS_REQUESTS,
    StripLightCapabilityTrial,
)
from .switchbot_strip_light_live_trial import BoundedStripStatusTransport


def run_from_environment(
    environment: Mapping[str, str] = os.environ,
) -> dict[str, object]:
    token = environment.get("SWITCHBOT_TOKEN", "").strip()
    secret = environment.get("SWITCHBOT_SECRET", "").strip()
    device_id = environment.get("SWITCHBOT_STRIP_LIGHT_3_DEVICE_ID", "").strip()
    if not token or not secret or not device_id:
        return {
            "target_alias": "strip-light-3",
            "reason": "private_runtime_configuration_incomplete",
            "persisted": False,
        }
    try:
        status_transport = BoundedStripStatusTransport(
            token,
            secret,
            maximum_status_requests=MAXIMUM_STATUS_REQUESTS,
        )
        command_transport = BoundedStripCapabilityCommandTransport(
            token,
            secret,
            device_id,
        )
        return StripLightCapabilityTrial(
            status_transport,
            command_transport,
            vendor_device_id=device_id,
        ).run().safe_summary()
    except Exception:
        return {
            "target_alias": "strip-light-3",
            "reason": "safe_trial_setup_failed",
            "persisted": False,
        }


def main() -> int:
    summary = run_from_environment()
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return (
        0
        if summary["reason"] == "all_capabilities_changed_and_restored"
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
