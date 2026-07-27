"""Environment runner for the explicitly approved E26-only trial."""

from __future__ import annotations

import json
import os
from collections.abc import Callable

import requests

from .e26_live_trial import BoundedE26TrialTransport, E26BrightnessTrial


def run_from_environment(
    *,
    request_get: Callable[..., requests.Response] = requests.get,
    request_post: Callable[..., requests.Response] = requests.post,
) -> dict[str, object]:
    token = os.environ.get("SWITCHBOT_TOKEN", "").strip()
    secret = os.environ.get("SWITCHBOT_SECRET", "").strip()
    if not token or not secret:
        return _unavailable("credentials_unavailable")
    try:
        transport = BoundedE26TrialTransport(
            token,
            secret,
            request_get=request_get,
            request_post=request_post,
        )
        return E26BrightnessTrial(transport).run().safe_summary()
    except Exception:
        return _unavailable("trial_preflight_unavailable")


def main() -> int:
    summary = run_from_environment()
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary.get("reason") == "changed_and_restored" else 1


def _unavailable(reason: str) -> dict[str, object]:
    return {
        "target_alias": "e26-smart-bulb",
        "reason": reason,
        "reader_qualified": False,
        "writer_qualified": False,
        "gate_qualified": False,
        "initial_state_eligible": False,
        "change_attempted": False,
        "change_confirmed": False,
        "restore_attempted": False,
        "restore_confirmed": False,
        "final_state_matches": False,
        "list_requests": 0,
        "status_requests": 0,
        "command_requests": 0,
        "stopped_after_e26": True,
        "persisted": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
