from dataclasses import dataclass

from hedp.environment import require_compatible_environment


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
