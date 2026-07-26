from dataclasses import dataclass
import os

from hedp.environment import require_compatible_environment


@dataclass(frozen=True)
class ModbusConfiguration:
    host: str
    port: int
    unit_id: int
    expected_serial: str
    continuity_id: str | None = None
    continuity_reason: str | None = None


@dataclass(frozen=True)
class EcoCuteConfiguration:
    host: str
    port: int = 3610
    instance_code: int = 1
    target_alias: str = "ecocute_main"


@dataclass(frozen=True)
class Configuration:
    base_url: str
    station_dn: str
    username: str
    password: str
    database_path: str

    @classmethod
    def from_environment(cls) -> "Configuration":
        suffixes = {
            "base_url": "FUSIONSOLAR_BASE_URL",
            "station_dn": "FUSIONSOLAR_STATION_DN",
            "username": "FUSIONSOLAR_USERNAME",
            "password": "FUSIONSOLAR_PASSWORD",
            "database_path": "DATABASE_PATH",
        }
        values = {
            field: require_compatible_environment(suffix)
            for field, suffix in suffixes.items()
        }
        return cls(**values)

    @staticmethod
    def device_dns_from_environment() -> list[str]:
        value = require_compatible_environment("FUSIONSOLAR_DEVICE_DNS")
        return list(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))

    @staticmethod
    def database_path_from_environment() -> str:
        return require_compatible_environment("DATABASE_PATH").strip()

    @staticmethod
    def ecocute_from_environment() -> EcoCuteConfiguration:
        host = require_compatible_environment("ECOCUTE_HOST").strip()
        values = {
            name: os.environ.get(
                f"SUMICORE_ECOCUTE_{name}",
                os.environ.get(f"HEDP_ECOCUTE_{name}", default),
            )
            for name, default in {
                "PORT": "3610",
                "INSTANCE_CODE": "1",
                "TARGET_ALIAS": "ecocute_main",
            }.items()
        }
        try:
            port = int(values["PORT"])
            instance_code = int(values["INSTANCE_CODE"])
        except (TypeError, ValueError) as error:
            raise RuntimeError(
                "EcoCute port and instance code must be integers"
            ) from error
        target_alias = values["TARGET_ALIAS"]
        if not 1 <= port <= 65535:
            raise RuntimeError("EcoCute port is out of range")
        if not 1 <= instance_code <= 255:
            raise RuntimeError("EcoCute instance code is out of range")
        if not target_alias or not target_alias.strip():
            raise RuntimeError("EcoCute target alias must not be empty")
        return EcoCuteConfiguration(
            host=host,
            port=port,
            instance_code=instance_code,
            target_alias=target_alias.strip(),
        )

    @staticmethod
    def battery_dc_from_environment() -> tuple[str, str]:
        values = (
            require_compatible_environment("FUSIONSOLAR_BATTERY_DN").strip(),
            require_compatible_environment("FUSIONSOLAR_BATTERY_SIGIDS").strip(),
        )
        device_dn, sigids = values
        return device_dn, sigids

    @staticmethod
    def modbus_from_environment() -> ModbusConfiguration:
        host = require_compatible_environment(
            "FUSIONSOLAR_MODBUS_HOST"
        ).strip()
        expected_serial = require_compatible_environment(
            "FUSIONSOLAR_MODBUS_EXPECTED_SERIAL"
        ).strip()
        try:
            port = int(
                require_compatible_environment("FUSIONSOLAR_MODBUS_PORT")
            )
            unit_id = int(
                require_compatible_environment("FUSIONSOLAR_MODBUS_UNIT_ID")
            )
        except ValueError as error:
            raise RuntimeError(
                "FusionSolar Modbus port and unit ID must be integers"
            ) from error
        if not 1 <= port <= 65535:
            raise RuntimeError("FusionSolar Modbus port is out of range")
        if not 0 <= unit_id <= 247:
            raise RuntimeError("FusionSolar Modbus unit ID is out of range")
        if not expected_serial:
            raise RuntimeError(
                "FusionSolar Modbus expected serial must not be empty"
            )
        continuity_id = os.environ.get("SUMICORE_FUSIONSOLAR_MODBUS_CONTINUITY_ID")
        if continuity_id is None:
            continuity_id = os.environ.get("HEDP_FUSIONSOLAR_MODBUS_CONTINUITY_ID")
        continuity_reason = None
        if continuity_id is not None:
            if len(continuity_id) != 32 or any(
                character not in "0123456789abcdef" for character in continuity_id
            ):
                raise RuntimeError("FusionSolar Modbus continuity ID is invalid")
            continuity_reason = os.environ.get(
                "SUMICORE_FUSIONSOLAR_MODBUS_CONTINUITY_REASON",
                os.environ.get("HEDP_FUSIONSOLAR_MODBUS_CONTINUITY_REASON"),
            )
            if continuity_reason not in {
                "initial",
                "continuous",
                "boot_changed",
                "scheduling_gap",
                "boot_evidence_unavailable",
                "boot_evidence_recovered",
            }:
                raise RuntimeError("FusionSolar Modbus continuity reason is invalid")
        return ModbusConfiguration(
            host=host,
            port=port,
            unit_id=unit_id,
            expected_serial=expected_serial,
            continuity_id=continuity_id,
            continuity_reason=continuity_reason,
        )
