"""One-shot, non-persistent runner for the bounded SwitchBot E26 probe."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import requests

from hedp.environment import get_compatible_environment

from .household import SwitchBotHouseholdConfiguration
from .probe import (
    BoundedSwitchBotReadTransport,
    PendingE26Probe,
    ProbeDisposition,
)
from .secondary_state import (
    RegistrationStatus,
    SecondaryDeviceKind,
    SecondaryDeviceRegistration,
)


_SAFE_ALIAS = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class ProbeRunnerReport:
    """Safe internal diagnostics; never includes response values or identifiers."""

    public_summary: dict[str, object]
    disposition: ProbeDisposition
    reason: str
    request_counts: tuple[int, int]
    exit_code: int

    def safe_internal_summary(self) -> dict[str, object]:
        return {
            **self.public_summary,
            "disposition": self.disposition.value,
            "reason": self.reason,
            "list_requests": self.request_counts[0],
            "status_requests": self.request_counts[1],
        }


def run_from_environment(
    *,
    request_get: Callable[..., requests.Response] = requests.get,
) -> dict[str, object]:
    """Run once using environment-injected secrets and return only safe output."""

    return run_report_from_environment(request_get=request_get).public_summary



def run_report_from_environment(
    *,
    request_get: Callable[..., requests.Response] = requests.get,
) -> ProbeRunnerReport:
    """Return bounded request counts and fixed reasons without private data."""

    alias = _probe_alias()
    transport: BoundedSwitchBotReadTransport | None = None
    try:
        token = os.environ.get("SWITCHBOT_TOKEN", "").strip()
        secret = os.environ.get("SWITCHBOT_SECRET", "").strip()
        if not token or not secret:
            raise RuntimeError("credentials unavailable")

        household = SwitchBotHouseholdConfiguration.from_environment()
        configured = tuple(
            item
            for item in household.secondary_devices
            if item.kind is SecondaryDeviceKind.E26_SMART_BULB
        )
        if len(configured) > 1:
            raise RuntimeError("probe target is not unique")
        registration = (
            configured[0]
            if configured
            else SecondaryDeviceRegistration(
                alias,
                SecondaryDeviceKind.E26_SMART_BULB,
                RegistrationStatus.PENDING_REGISTRATION,
            )
        )

        known_ids = _known_ids_from_read_only_database()
        known_registrations = tuple(
            SecondaryDeviceRegistration(
                f"known-{index}",
                SecondaryDeviceKind.MOTION_SENSOR,
                RegistrationStatus.OBSERVABLE,
                vendor_device_id,
            )
            for index, vendor_device_id in enumerate(sorted(known_ids))
        )
        transport = BoundedSwitchBotReadTransport(
            token,
            secret,
            timeout_seconds=5,
            response_byte_cap=128 * 1024,
            maximum_status_requests=1,
            wall_clock_deadline_seconds=12,
            request_get=request_get,
        )
        result = PendingE26Probe(transport).run(
            registration,
            known_registrations=known_registrations,
            permit_unique_difference_link=True,
        )
        exit_code = 1 if result.disposition is ProbeDisposition.BLOCKED else 0
        return ProbeRunnerReport(
            result.safe_summary(),
            result.disposition,
            result.reason,
            transport.request_counts,
            exit_code,
        )
    except Exception:
        return ProbeRunnerReport(
            _pending_unknown(alias),
            ProbeDisposition.PENDING_REGISTRATION,
            (
                "probe_transport_unavailable"
                if transport is not None
                else "probe_preflight_unavailable"
            ),
            transport.request_counts if transport is not None else (0, 0),
            1,
        )


def _known_ids_from_read_only_database() -> set[str]:
    value = get_compatible_environment("DATABASE_PATH").strip()
    if not value:
        raise RuntimeError("SwitchBot probe read-only baseline is unavailable")
    path = Path(value).expanduser()
    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        try:
            rows = connection.execute(
                "SELECT device_id FROM switchbot_devices"
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as error:
        raise RuntimeError(
            "SwitchBot probe read-only baseline is unavailable"
        ) from error
    return {
        str(row[0])
        for row in rows
        if row and isinstance(row[0], str) and row[0]
    }


def _pending_unknown(alias: str) -> dict[str, object]:
    return {
        "target_alias": alias,
        "device_type": None,
        "status_fields": [],
        "quality": "unknown",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "persisted": False,
    }


def main() -> int:
    report = run_report_from_environment()
    print(json.dumps(report.public_summary, ensure_ascii=False, sort_keys=True))
    return report.exit_code


def _probe_alias() -> str:
    value = os.environ.get("SWITCHBOT_E26_PROBE_ALIAS", "e26-pending").strip()
    return value if _SAFE_ALIAS.fullmatch(value) is not None else "e26-pending"


if __name__ == "__main__":
    raise SystemExit(main())
