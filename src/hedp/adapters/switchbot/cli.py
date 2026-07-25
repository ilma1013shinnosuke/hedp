from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path

from hedp.adapters.switchbot.client import SwitchBotClient
from hedp.adapters.switchbot.household import SwitchBotHouseholdConfiguration
from hedp.adapters.switchbot.importer import SwitchBotImporter
from hedp.adapters.switchbot.service import SwitchBotService
from hedp.adapters.switchbot.storage import SwitchBotStorage
from hedp.environment import require_compatible_environment


def add_switchbot_parser(subparsers: argparse._SubParsersAction) -> None:
    root = subparsers.add_parser("switchbot")
    groups = root.add_subparsers(dest="switchbot_group", required=True)
    devices = groups.add_parser("devices")
    device_actions = devices.add_subparsers(dest="switchbot_action", required=True)
    refresh = device_actions.add_parser("refresh")
    refresh.add_argument("--dry-run", action="store_true")
    for action in ("list", "names", "locations"):
        command = device_actions.add_parser(action)
        command.add_argument("--details", action="store_true")
    for action in ("enable", "disable"):
        command = device_actions.add_parser(action)
        command.add_argument("device_id")
    collect = groups.add_parser("collect")
    collect.add_argument("--dry-run", action="store_true")
    imports = groups.add_parser("import")
    import_actions = imports.add_subparsers(dest="switchbot_action", required=True)
    for action in ("inspect", "run"):
        command = import_actions.add_parser(action)
        command.add_argument("path", type=Path)
        command.add_argument("--details", action="store_true")
        if action == "run":
            command.add_argument("--dry-run", action="store_true")
    import_actions.add_parser("report").add_argument(
        "--details", action="store_true"
    )
    observations = groups.add_parser("observations")
    observation_actions = observations.add_subparsers(
        dest="switchbot_action", required=True
    )
    observation_actions.add_parser("latest").add_argument(
        "--details", action="store_true"
    )
    period = observation_actions.add_parser("range")
    period.add_argument("device_id")
    period.add_argument("--start", required=True)
    period.add_argument("--end", required=True)
    period.add_argument("--details", action="store_true")
    groups.add_parser("gaps").add_argument("--details", action="store_true")
    hourly = groups.add_parser("hourly")
    hourly.add_subparsers(dest="switchbot_action", required=True).add_parser(
        "rebuild"
    )


def run_switchbot(arguments: argparse.Namespace) -> int:
    database_path = require_compatible_environment("DATABASE_PATH").strip()
    storage = SwitchBotStorage(database_path)
    storage.connect()
    try:
        household = SwitchBotHouseholdConfiguration.from_environment()
        group = arguments.switchbot_group
        action = getattr(arguments, "switchbot_action", None)
        if group == "devices" and action in {"refresh"}:
            service = SwitchBotService(_client(), storage, household)
            report = service.refresh_devices(dry_run=arguments.dry_run)
            print(f"Physical devices: {len(report['physical'])}")
            print(f"Infrared remotes: {len(report['infrared'])}")
            return 0
        if group == "collect":
            report = SwitchBotService(_client(), storage, household).collect(
                dry_run=arguments.dry_run
            )
            succeeded = sum(item["success"] for item in report["results"])
            print(f"Devices: {report['devices']}")
            print(f"Succeeded: {succeeded}")
            print(f"Failed: {report['devices'] - succeeded}")
            return 1 if succeeded != report["devices"] else 0
        if group == "import":
            importer = SwitchBotImporter(storage, household.filename_device_ids)
            if action == "inspect":
                report = importer.inspect(arguments.path)
            elif action == "run":
                report = importer.run(arguments.path, dry_run=arguments.dry_run)
            else:
                report = {"files": storage.rows(
                    "SELECT * FROM switchbot_import_runs ORDER BY import_id"
                )}
            if arguments.details:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                print(
                    json.dumps(
                        _safe_import_summary(report),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            blocked = report.get("status") == "blocked" or any(
                item.get("status") == "blocked" for item in report["files"]
            )
            return 1 if blocked else 0
        if group == "devices":
            if action in {"enable", "disable"}:
                storage.set_enabled(arguments.device_id, action == "enable")
                print(f"Device target: {action}d")
                return 0
            table = {
                "list": "SELECT * FROM switchbot_devices ORDER BY current_api_name",
                "names": "SELECT * FROM switchbot_device_names ORDER BY device_id,valid_from",
                "locations": "SELECT * FROM switchbot_device_locations ORDER BY device_id,valid_from",
            }[action]
            rows = storage.rows(table)
            if arguments.details:
                _print_rows(rows)
            else:
                _print_safe_summary(rows, action)
            return 0
        if group == "observations":
            if action == "latest":
                query = """SELECT o.* FROM switchbot_observations o JOIN
                (SELECT device_id,max(observed_at_utc) observed_at_utc
                 FROM switchbot_observations GROUP BY device_id) x
                USING(device_id,observed_at_utc) ORDER BY device_id"""
                rows = storage.rows(query)
            else:
                rows = storage.rows(
                    "SELECT * FROM switchbot_observations WHERE device_id=? "
                    "AND observed_at_utc BETWEEN ? AND ? ORDER BY observed_at_utc",
                    (arguments.device_id, arguments.start, arguments.end),
                )
            if arguments.details:
                _print_rows(rows)
            else:
                _print_safe_summary(rows, "observations")
            return 0
        if group == "gaps":
            storage.rebuild_gaps()
            rows = storage.rows(
                "SELECT * FROM switchbot_data_gaps ORDER BY gap_start"
            )
            if arguments.details:
                _print_rows(rows)
            else:
                _print_safe_summary(rows, "gaps")
            return 0
        if group == "hourly":
            print(f"Hourly summaries: {storage.rebuild_hourly()}")
            return 0
        raise RuntimeError("Unknown SwitchBot command")
    finally:
        storage.close()


def _client() -> SwitchBotClient:
    token = os.environ.get("SWITCHBOT_TOKEN", "").strip()
    secret = os.environ.get("SWITCHBOT_SECRET", "").strip()
    if not token or not secret:
        raise RuntimeError("SWITCHBOT_TOKEN and SWITCHBOT_SECRET are required")
    return SwitchBotClient(token, secret)


def _print_rows(rows: list[dict[str, object]]) -> None:
    for row in rows:
        safe = {
            key: value
            for key, value in row.items()
            if key not in {"raw_payload_json", "existing_payload", "incoming_payload"}
        }
        if "device_id" in safe:
            safe["device_id"] = str(safe["device_id"])[-6:]
        if "hub_device_id" in safe:
            safe["hub_device_id"] = str(safe["hub_device_id"])[-6:]
        print(json.dumps(safe, ensure_ascii=False, sort_keys=True))


def _print_safe_summary(
    rows: list[dict[str, object]], kind: str
) -> None:
    device_count = len(
        {
            str(row["device_id"])
            for row in rows
            if row.get("device_id") is not None
        }
    )
    summary: dict[str, object] = {
        "schema": "sumicore.switchbot.safe-summary.v1",
        "kind": kind,
        "row_count": len(rows),
        "device_count": device_count,
    }
    safe_group_fields = {
        "list": ("device_type", "current_status"),
        "observations": (
            "observation_kind",
            "measurement_status",
            "online_status",
            "working_status",
        ),
        "gaps": ("likely_reason", "status"),
    }
    groups = {}
    for field in safe_group_fields.get(kind, ()):
        counts = Counter(
            str(row[field])
            for row in rows
            if row.get(field) is not None
        )
        if counts:
            groups[field] = dict(sorted(counts.items()))
    if groups:
        summary["groups"] = groups
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


def _safe_import_summary(report: dict[str, object]) -> dict[str, object]:
    files = report.get("files", [])
    file_reports = files if isinstance(files, list) else []
    numeric_fields = (
        "rows",
        "rows_read",
        "rows_inserted",
        "duplicates_skipped",
        "exact_duplicates_skipped",
        "timestamp_conflicts",
        "invalid_rows",
        "reversed_timestamps",
    )
    totals = {
        field: sum(
            int(item.get(field, 0))
            for item in file_reports
            if isinstance(item, dict)
            and isinstance(item.get(field, 0), int)
        )
        for field in numeric_fields
    }
    status_counts = Counter(
        str(item.get("status", "inspected"))
        for item in file_reports
        if isinstance(item, dict)
    )
    comparisons = report.get("comparisons", [])
    comparison_reports = (
        comparisons if isinstance(comparisons, list) else []
    )
    return {
        "schema": "sumicore.switchbot.safe-import-summary.v1",
        "status": str(report.get("status", "completed")),
        "file_count": len(file_reports),
        "comparison_count": len(comparison_reports),
        "comparison_failures": sum(
            1
            for item in comparison_reports
            if isinstance(item, dict) and item.get("identical") is False
        ),
        "status_counts": dict(sorted(status_counts.items())),
        "totals": totals,
    }
