"""One-shot anonymous runner for the bounded SwitchBot secondary fleet probe."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime, timezone

import requests

from .fleet_probe import SecondaryFleetProbe
from .probe import BoundedSwitchBotReadTransport
from .secondary_state import SecondaryDeviceKind


_ALIASES = (
    ("motion-sensor", SecondaryDeviceKind.MOTION_SENSOR),
    ("presence-sensor-pro", SecondaryDeviceKind.PRESENCE_SENSOR_PRO),
    ("e26-smart-bulb", SecondaryDeviceKind.E26_SMART_BULB),
    ("strip-light-3", SecondaryDeviceKind.STRIP_LIGHT_3),
)


def run_from_environment(
    *,
    request_get: Callable[..., requests.Response] = requests.get,
) -> dict[str, object]:
    """Use environment-injected secrets and return no values or identifiers."""

    transport: BoundedSwitchBotReadTransport | None = None
    try:
        token = os.environ.get("SWITCHBOT_TOKEN", "").strip()
        secret = os.environ.get("SWITCHBOT_SECRET", "").strip()
        if not token or not secret:
            raise RuntimeError("credentials unavailable")
        transport = BoundedSwitchBotReadTransport(
            token,
            secret,
            timeout_seconds=5,
            response_byte_cap=128 * 1024,
            maximum_status_requests=4,
            wall_clock_deadline_seconds=20,
            request_get=request_get,
        )
        report = SecondaryFleetProbe(transport).run()
        summary = report.safe_summary()
        summary["list_requests"] = transport.request_counts[0]
        summary["status_requests"] = transport.request_counts[1]
        summary["probe_status"] = "completed"
        summary["reason"] = "probe_completed"
        return summary
    except Exception as error:
        observed_at = datetime.now(timezone.utc).isoformat()
        request_counts = (
            transport.request_counts if transport is not None else (0, 0)
        )
        return {
            "devices": [
                {
                    "target_alias": alias,
                    "device_type": None,
                    "status_fields": [],
                    "quality": "unknown",
                    "observed_at": observed_at,
                    "persisted": False,
                }
                for alias, _ in _ALIASES
            ],
            "observed_device_types": [],
            "persisted": False,
            "list_requests": request_counts[0],
            "status_requests": request_counts[1],
            "probe_status": "unavailable",
            "reason": _safe_failure_reason(error, transport),
        }


def main() -> int:
    summary = run_from_environment()
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["probe_status"] == "completed" else 1


def _safe_failure_reason(
    error: Exception,
    transport: BoundedSwitchBotReadTransport | None,
) -> str:
    """Classify failures without returning URLs, credentials, or response data."""

    if transport is None:
        return "probe_preflight_unavailable"
    if isinstance(error, (TimeoutError, requests.Timeout)):
        return "probe_timeout"
    if isinstance(error, requests.HTTPError):
        response = error.response
        status_code = response.status_code if response is not None else None
        if status_code == 401:
            return "probe_authentication_rejected"
        if status_code == 403:
            return "probe_access_forbidden"
        if status_code == 429:
            return "probe_rate_limited"
        if status_code is not None and 500 <= status_code < 600:
            return "probe_vendor_unavailable"
        return "probe_http_error"
    if isinstance(error, requests.RequestException):
        return "probe_transport_unavailable"
    if isinstance(error, PermissionError):
        return "probe_limit_blocked"
    if isinstance(error, ValueError):
        return "probe_response_invalid"
    return "probe_transport_unavailable"


if __name__ == "__main__":
    raise SystemExit(main())
