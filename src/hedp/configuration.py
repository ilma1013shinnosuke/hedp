from dataclasses import dataclass

from hedp.environment import require_compatible_environment


@dataclass(frozen=True)
class ModbusConfiguration:
    host: str
    port: int
    unit_id: int
    expected_serial: str


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
        return ModbusConfiguration(
            host=host,
            port=port,
            unit_id=unit_id,
            expected_serial=expected_serial,
        )
