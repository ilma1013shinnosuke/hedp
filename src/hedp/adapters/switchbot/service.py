from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from hedp.adapters.switchbot.client import SwitchBotClient
from hedp.adapters.switchbot.household import SwitchBotHouseholdConfiguration
from hedp.adapters.switchbot.profiles import (
    expected_interval_seconds,
    normalize_registered_secondary_status,
    normalize_status,
    success_raw_retention_reasons,
)
from hedp.adapters.switchbot.secondary_state import (
    RegistrationStatus,
    SecondaryDeviceRegistration,
)
from hedp.adapters.switchbot.storage import SwitchBotStorage


TOKYO = ZoneInfo("Asia/Tokyo")


class SwitchBotService:
    def __init__(
        self,
        client: SwitchBotClient,
        storage: SwitchBotStorage,
        household: SwitchBotHouseholdConfiguration | None = None,
    ) -> None:
        self.client = client
        self.storage = storage
        self.household = household or SwitchBotHouseholdConfiguration()

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
            self.storage.reconcile_devices(
                {
                    str(device["deviceId"])
                    for device in physical
                    if isinstance(device, dict) and device.get("deviceId")
                }
            )
            self._ensure_household_history()
        return {"physical": physical, "infrared": infrared}

    def collect(self, *, dry_run: bool = False) -> dict[str, Any]:
        listing = self.refresh_devices(dry_run=dry_run)
        collected_at = datetime.now(timezone.utc)
        results = []
        registry = self.household.secondary_registry
        seen_secondary_aliases = set()
        for device in listing["physical"]:
            device_id = str(device.get("deviceId", ""))
            registration = registry.resolve_vendor_id(device_id)
            if registration is not None:
                seen_secondary_aliases.add(registration.target_alias)
                if (
                    registration.registration_status
                    is not RegistrationStatus.OBSERVABLE
                ):
                    results.append(
                        {
                            "target_alias": registration.target_alias,
                            "secondary_device_kind": registration.kind.value,
                            "registration_status": (
                                registration.registration_status.value
                            ),
                            "success": None,
                            "status_body_empty": None,
                            "error": None,
                        }
                    )
                    continue
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
                observation = (
                    self._secondary_observation(
                        registration,
                        response,
                        collected_at,
                    )
                    if registration is not None
                    else self._observation(device, response, collected_at)
                )
                result["raw_retention_reasons"] = observation.pop(
                    "_raw_retention_reasons"
                )
                result["storage_result"] = self.storage.insert_observation(observation)
                self.storage.commit()
            if not dry_run:
                self.storage.record_collection_event(
                    device_id,
                    collected_at,
                    success=success,
                    status_body_empty=result["status_body_empty"],
                    error_type=error,
                    raw_payload_json=(
                        json.dumps(response, ensure_ascii=False)
                        if response is not None and not success
                        else None
                    ),
                )
            results.append(result)
        for registration in registry.registrations:
            if (
                registration.registration_status is RegistrationStatus.OBSERVABLE
                or registration.target_alias in seen_secondary_aliases
            ):
                continue
            results.append(
                {
                    "target_alias": registration.target_alias,
                    "secondary_device_kind": registration.kind.value,
                    "registration_status": registration.registration_status.value,
                    "success": None,
                    "status_body_empty": None,
                    "error": None,
                }
            )
        return {"devices": len(listing["physical"]), "results": results}

    @staticmethod
    def _observation(
        device: dict[str, Any], response: dict[str, Any], collected_at: datetime
    ) -> dict[str, Any]:
        body = response.get("body")
        normalized = normalize_status(
            device,
            body if isinstance(body, dict) else {},
            observed_at=collected_at,
        )
        raw_retention_reasons = success_raw_retention_reasons(
            str(device.get("deviceType", "")),
            body,
            normalized,
        )
        return {
            "device_id": str(device["deviceId"]),
            "observed_at_utc": collected_at.isoformat(),
            "observed_at_local": collected_at.astimezone(TOKYO).isoformat(),
            "timezone": "Asia/Tokyo",
            "observation_kind": "status_snapshot",
            "temperature_c": normalized["temperature_c"],
            "relative_humidity_percent": normalized["relative_humidity_percent"],
            "co2_ppm": normalized["co2_ppm"],
            "battery_percent": normalized["battery_percent"],
            "power_state": normalized["power_state"],
            "electric_current_ma": normalized["electric_current_ma"],
            "voltage_v": normalized["voltage_v"],
            "power_consumed_daily_w": normalized["power_consumed_daily_w"],
            "usage_minutes_of_day": normalized["usage_minutes_of_day"],
            "online_status": normalized["online_status"],
            "working_status": normalized["working_status"],
            "robot_working_status": normalized["robot_working_status"],
            "charging_status": normalized["charging_status"],
            "task_status": normalized["task_status"],
            "water_base_battery_percent": normalized["water_base_battery_percent"],
            "status_quality": normalized["status_quality"],
            "source": "switchbot_api_v1_1",
            "source_precision": "collection_time_snapshot",
            "expected_interval_seconds": expected_interval_seconds(
                str(device.get("deviceType", ""))
            ),
            "collection_method": "open_api_v1_1",
            "measurement_status": normalized["measurement_status"],
            "raw_payload_json": (
                json.dumps(response, ensure_ascii=False)
                if raw_retention_reasons
                else None
            ),
            "_raw_retention_reasons": raw_retention_reasons,
        }

    @staticmethod
    def _secondary_observation(
        registration: SecondaryDeviceRegistration,
        response: dict[str, Any],
        collected_at: datetime,
    ) -> dict[str, Any]:
        body = response.get("body")
        normalized, observation, raw_retention_reasons = (
            normalize_registered_secondary_status(
                registration,
                body if isinstance(body, dict) else None,
                observed_at=collected_at,
                received_at=collected_at,
                evaluated_at=collected_at,
                stale_after_seconds=normalized_secondary_stale_after_seconds(
                    registration
                ),
            )
        )
        return {
            "device_id": registration.vendor_device_id,
            "device_alias": registration.target_alias,
            "secondary_device_kind": registration.kind.value,
            "secondary_source": observation.source.value,
            "secondary_quality": observation.quality.value,
            "secondary_state_json": json.dumps(
                observation.to_storage_dict(),
                ensure_ascii=False,
                sort_keys=True,
            ),
            "observed_at_utc": collected_at.isoformat(),
            "observed_at_local": collected_at.astimezone(TOKYO).isoformat(),
            "timezone": "Asia/Tokyo",
            "observation_kind": "secondary_status_snapshot",
            "power_state": normalized["power_state"],
            "status_quality": normalized["status_quality"],
            "source": "switchbot_api_v1_1",
            "source_precision": "collection_time_snapshot",
            "expected_interval_seconds": normalized["expected_interval_seconds"],
            "collection_method": "open_api_v1_1",
            "measurement_status": normalized["measurement_status"],
            "raw_payload_json": (
                json.dumps(response, ensure_ascii=False)
                if raw_retention_reasons
                else None
            ),
            "_raw_retention_reasons": raw_retention_reasons,
        }

    def _ensure_household_history(self) -> None:
        for item in self.household.location_history:
            self.storage.set_location(
                item["device_id"],
                item["location"],
                item["purpose"],
                item["valid_from"],
                valid_to=item.get("valid_to"),
                precision=item.get("precision", "day"),
                source=item.get("source", "local_household_config"),
                notes=item.get("notes"),
            )
        for item in self.household.name_history:
            self.storage.set_name_history(
                item["device_id"],
                item["name"],
                item["valid_from"],
                valid_to=item.get("valid_to"),
                source=item.get("source", "local_household_config"),
            )


def normalized_secondary_stale_after_seconds(
    registration: SecondaryDeviceRegistration,
) -> int:
    """Keep stale policy explicit and independent from a guessed deviceType."""

    del registration
    return 7200
