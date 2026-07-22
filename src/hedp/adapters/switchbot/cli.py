from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from hedp.adapters.switchbot.client import SwitchBotClient
from hedp.adapters.switchbot.household import SwitchBotHouseholdConfiguration
from hedp.adapters.switchbot.importer import SwitchBotImporter
from hedp.adapters.switchbot.service import SwitchBotService
from hedp.adapters.switchbot.storage import SwitchBotStorage


def add_switchbot_parser(subparsers: argparse._SubParsersAction) -> None:
    root = subparsers.add_parser("switchbot")
    groups = root.add_subparsers(dest="switchbot_group", required=True)
    devices = groups.add_parser("devices")
    device_actions = devices.add_subparsers(dest="switchbot_action", required=True)
    refresh = device_actions.add_parser("refresh")
    refresh.add_argument("--dry-run", action="store_true")
    device_actions.add_parser("list")
    device_actions.add_parser("names")
    device_actions.add_parser("locations")
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
        if action == "run":
            command.add_argument("--dry-run", action="store_true")
    import_actions.add_parser("report")
    observations = groups.add_parser("observations")
    observation_actions = observations.add_subparsers(
        dest="switchbot_action", required=True
    )
    observation_actions.add_parser("latest")
    period = observation_actions.add_parser("range")
    period.add_argument("device_id")
    period.add_argument("--start", required=True)
    period.add_argument("--end", required=True)
    groups.add_parser("gaps")
    hourly = groups.add_parser("hourly")
    hourly.add_subparsers(dest="switchbot_action", required=True).add_parser(
        "rebuild"
    )


def run_switchbot(arguments: argparse.Namespace) -> int:
    database_path = os.environ.get("HEDP_DATABASE_PATH", "").strip()
    if not database_path:
        raise RuntimeError("HEDP_DATABASE_PATH is required")
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
            print(json.dumps(report, ensure_ascii=False, indent=2))
            blocked = report.get("status") == "blocked" or any(
                item.get("status") == "blocked" for item in report["files"]
            )
            return 1 if blocked else 0
        if group == "devices":
            if action in {"enable", "disable"}:
                storage.set_enabled(arguments.device_id, action == "enable")
                print(f"Device {arguments.device_id[-6:]}: {action}d")
                return 0
            table = {
                "list": "SELECT * FROM switchbot_devices ORDER BY current_api_name",
                "names": "SELECT * FROM switchbot_device_names ORDER BY device_id,valid_from",
                "locations": "SELECT * FROM switchbot_device_locations ORDER BY device_id,valid_from",
            }[action]
            _print_rows(storage.rows(table))
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
            _print_rows(rows)
            return 0
        if group == "gaps":
            storage.rebuild_gaps()
            _print_rows(storage.rows(
                "SELECT * FROM switchbot_data_gaps ORDER BY gap_start"
            ))
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
