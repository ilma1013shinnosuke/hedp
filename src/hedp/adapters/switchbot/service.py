from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from hedp.adapters.switchbot.client import SwitchBotClient
from hedp.adapters.switchbot.storage import SwitchBotStorage


TOKYO = ZoneInfo("Asia/Tokyo")
CONFIRMED_LOCATIONS = {
    "D508ED4BD39F": ("2Fトイレ", "温湿度", "2023-03-12"),
    "E2042421588D": ("クローゼット", "温湿度", "2023-03-12"),
    "F7F4263069C0": ("バスルーム", "温湿度", "2023-06-30"),
    "F6AB0E1D5517": ("フリースペース", "温湿度", "2023-03-12"),
    "E888C195493C": ("リビング", "温湿度", "2021-06-24"),
    "D9CF767A857F": ("外気温", "屋外温湿度", "2023-03-12"),
    "EA56DAD63611": ("玄関", "温湿度", "2021-07-03"),
    "D064886F78EF": ("書斎", "温湿度", "2023-03-12"),
    "B0E9FE558B5A": ("リビング", "温湿度・CO2", "2026-07-21"),
    "B0E9FE558B6C": ("寝室", "温湿度・CO2", "2026-07-21"),
    "E4BD97F06AB2": ("寝室", "温湿度", "2026-07-21"),
}


class SwitchBotService:
    def __init__(self, client: SwitchBotClient, storage: SwitchBotStorage) -> None:
        self.client = client
        self.storage = storage

    def refresh_devices(self, *, dry_run: bool = False) -> dict[str, Any]:
        response = self.client.devices()
        body = response.get("body")
        if response.get("statusCode") != 100 or not isinstance(body, dict):
            raise RuntimeError("SwitchBot device list request failed")
        physical = body.get("deviceList", [])
        infrared = body.get("infraredRemoteList", [])
        if not isinstance(physical, list) or not isinstance(infrared, list):
            raise ValueError("SwitchBot device list has an unexpected shape")
        now = datetime.now(timezone.utc)
        if not dry_run:
            for device in physical:
                if isinstance(device, dict) and device.get("deviceId"):
                    self.storage.upsert_device(device, now)
            self.storage.reconcile_devices({
                str(device["deviceId"])
                for device in physical
                if isinstance(device, dict) and device.get("deviceId")
            })
            self._ensure_confirmed_location_history()
        return {"physical": physical, "infrared": infrared}

    def collect(self, *, dry_run: bool = False) -> dict[str, Any]:
        listing = self.refresh_devices(dry_run=dry_run)
        collected_at = datetime.now(timezone.utc)
        results = []
        for device in listing["physical"]:
            device_id = str(device.get("deviceId", ""))
            try:
                response = self.client.status(device_id)
                success = response.get("statusCode") == 100
                error = None if success else "api_status"
            except Exception as exc:
                response = None
                success = False
                error = type(exc).__name__
            result = {
                "device_id": device_id,
                "success": success,
                "status_body_empty": response is not None
                and response.get("body") == {},
                "error": error,
            }
            if success and response is not None and not dry_run:
                observation = self._observation(device, response, collected_at)
                result["storage_result"] = self.storage.insert_observation(
                    observation
                )
                self.storage.commit()
            if not dry_run:
                self.storage.record_collection_event(
                    device_id, collected_at, success=success,
                    status_body_empty=result["status_body_empty"],
                    error_type=error,
                    raw_payload_json=(
                        json.dumps(response, ensure_ascii=False)
                        if response is not None else None
                    ),
                )
            results.append(result)
        return {"devices": len(listing["physical"]), "results": results}

    @staticmethod
    def _observation(
        device: dict[str, Any], response: dict[str, Any], collected_at: datetime
    ) -> dict[str, Any]:
        body = response.get("body")
        body = body if isinstance(body, dict) else {}
        zero_unavailable = all(body.get(key) == 0 for key in (
            "temperature", "humidity", "battery"
        )) and all(key in body for key in ("temperature", "humidity", "battery"))
        return {
            "device_id": str(device["deviceId"]),
            "observed_at_utc": collected_at.isoformat(),
            "observed_at_local": collected_at.astimezone(TOKYO).isoformat(),
            "timezone": "Asia/Tokyo",
            "observation_kind": "status_snapshot",
            "temperature_c": None if zero_unavailable else body.get("temperature"),
            "relative_humidity_percent": None
            if zero_unavailable else body.get("humidity"),
            "co2_ppm": body.get("CO2"),
            "battery_percent": body.get("battery"),
            "power_state": body.get("power"),
            "electric_current_ma": body.get("electricCurrent"),
            "voltage_v": body.get("voltage"),
            "power_consumed_daily_w": body.get("weight"),
            "usage_minutes_of_day": body.get("electricityOfDay"),
            "online_status": body.get("onlineStatus"),
            "working_status": body.get("workingStatus"),
            "source": "switchbot_api_v1_1",
            "source_precision": "snapshot",
            "expected_interval_seconds": 3600,
            "collection_method": "open_api_v1_1",
            "measurement_status": "battery_depleted_or_unavailable"
            if zero_unavailable else "observed",
            "raw_payload_json": json.dumps(response, ensure_ascii=False),
        }

    def _ensure_confirmed_location_history(self) -> None:
        for device_id, (location, purpose, valid_from) in CONFIRMED_LOCATIONS.items():
            self.storage.set_location(
                device_id, location, purpose, valid_from, precision="day",
                source="user_confirmed_inventory",
            )
        device_id = "C1BD4CEC2D7B"
        self.storage.set_name_history(
            device_id, "車内", "2023-10-23", valid_to="2026-07-21",
            source="historical_export_and_user_report",
        )
        self.storage.set_location(
            device_id, "車内", "車内温湿度", "2023-10-23",
            valid_to="2026-07-21", precision="day",
            source="historical_export_and_user_report",
            notes="履歴CSVの期間は車内設置",
        )
        self.storage.set_location(
            device_id, "外", "屋外温湿度", "2026-07-21",
            precision="day", source="user_report",
            notes="ユーザー申告による移設日",
        )
