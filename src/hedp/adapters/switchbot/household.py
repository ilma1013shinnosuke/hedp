from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from hedp.adapters.switchbot.secondary_state import (
    RegistrationStatus,
    SecondaryDeviceKind,
    SecondaryDeviceRegistration,
    SecondaryDeviceRegistry,
)
from hedp.environment import get_compatible_environment


@dataclass(frozen=True)
class SwitchBotHouseholdConfiguration:
    filename_device_ids: dict[str, str] = field(default_factory=dict)
    location_history: tuple[dict[str, str], ...] = ()
    name_history: tuple[dict[str, str], ...] = ()
    secondary_devices: tuple[SecondaryDeviceRegistration, ...] = field(
        default=(),
        repr=False,
    )

    @property
    def secondary_registry(self) -> SecondaryDeviceRegistry:
        return SecondaryDeviceRegistry(self.secondary_devices)

    @classmethod
    def from_environment(cls) -> "SwitchBotHouseholdConfiguration":
        value = get_compatible_environment("SWITCHBOT_HOUSEHOLD_CONFIG_PATH").strip()
        return cls.from_file(Path(value)) if value else cls()

    @classmethod
    def from_file(cls, path: Path) -> "SwitchBotHouseholdConfiguration":
        if not path.is_absolute():
            raise RuntimeError("SwitchBot household config path must be absolute")
        try:
            stat = path.stat()
            if os.name != "nt" and stat.st_mode & 0o077:
                raise RuntimeError(
                    "SwitchBot household config permissions must be 0600"
                )
            if stat.st_size > 1024 * 1024:
                raise RuntimeError("SwitchBot household config exceeds 1 MiB")
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise RuntimeError(f"SwitchBot household config not found: {path}") from error
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"SwitchBot household config is not valid JSON: {path}"
            ) from error
        if not isinstance(payload, dict):
            raise RuntimeError("SwitchBot household config must be a JSON object")
        return cls(
            cls._string_mapping(
                payload.get("filename_device_ids", {}), "filename_device_ids"
            ),
            cls._history(
                payload.get("location_history", []),
                "location_history",
                required=("device_id", "location", "purpose", "valid_from"),
            ),
            cls._history(
                payload.get("name_history", []),
                "name_history",
                required=("device_id", "name", "valid_from"),
            ),
            cls._secondary_devices(payload.get("secondary_devices", [])),
        )

    @staticmethod
    def _string_mapping(value: Any, field_name: str) -> dict[str, str]:
        if not isinstance(value, dict):
            raise RuntimeError(f"{field_name} must be a JSON object")
        result = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise RuntimeError(f"{field_name} contains an empty key")
            if not isinstance(item, str) or not item.strip():
                raise RuntimeError(f"{field_name}.{key} must be a non-empty string")
            result[key.strip()] = item.strip()
        return result

    @staticmethod
    def _history(
        value: Any, field_name: str, *, required: tuple[str, ...]
    ) -> tuple[dict[str, str], ...]:
        if not isinstance(value, list):
            raise RuntimeError(f"{field_name} must be a JSON array")
        result = []
        optional = {"valid_to", "source", "notes", "precision"}
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                raise RuntimeError(f"{field_name}[{index}] must be a JSON object")
            unknown = set(item) - set(required) - optional
            if unknown:
                names = ", ".join(sorted(unknown))
                raise RuntimeError(f"{field_name}[{index}] has unknown fields: {names}")
            normalized = {}
            for key, raw in item.items():
                if not isinstance(raw, str) or not raw.strip():
                    raise RuntimeError(
                        f"{field_name}[{index}].{key} must be a non-empty string"
                    )
                normalized[key] = raw.strip()
            missing = [key for key in required if key not in normalized]
            if missing:
                names = ", ".join(missing)
                raise RuntimeError(f"{field_name}[{index}] is missing: {names}")
            for key in ("valid_from", "valid_to"):
                if key in normalized:
                    try:
                        date.fromisoformat(normalized[key])
                    except ValueError as error:
                        raise RuntimeError(
                            f"{field_name}[{index}].{key} must use YYYY-MM-DD"
                        ) from error
            result.append(normalized)
        return tuple(result)

    @staticmethod
    def _secondary_devices(value: Any) -> tuple[SecondaryDeviceRegistration, ...]:
        if not isinstance(value, list):
            raise RuntimeError("secondary_devices must be a JSON array")
        registrations = []
        allowed = {
            "target_alias",
            "kind",
            "registration_status",
            "vendor_device_id",
        }
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                raise RuntimeError(
                    f"secondary_devices[{index}] must be a JSON object"
                )
            unknown = set(item) - allowed
            if unknown:
                names = ", ".join(sorted(unknown))
                raise RuntimeError(
                    f"secondary_devices[{index}] has unknown fields: {names}"
                )
            try:
                alias = item["target_alias"]
                kind = SecondaryDeviceKind(item["kind"])
                status = RegistrationStatus(item["registration_status"])
            except KeyError as error:
                raise RuntimeError(
                    f"secondary_devices[{index}] is missing: {error.args[0]}"
                ) from error
            except (TypeError, ValueError) as error:
                raise RuntimeError(
                    f"secondary_devices[{index}] has an invalid kind or status"
                ) from error
            vendor_device_id = item.get("vendor_device_id")
            try:
                registrations.append(
                    SecondaryDeviceRegistration(
                        alias,
                        kind,
                        status,
                        vendor_device_id,
                    )
                )
            except (TypeError, ValueError) as error:
                raise RuntimeError(
                    f"secondary_devices[{index}] is invalid"
                ) from error
        try:
            SecondaryDeviceRegistry(tuple(registrations))
        except ValueError as error:
            raise RuntimeError("secondary_devices contains duplicate registrations") from error
        return tuple(registrations)
