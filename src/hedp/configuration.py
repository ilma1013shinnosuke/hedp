import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Configuration:
    CONFIRMED_BATTERY_DEVICE_DN = "NE=33812831"
    CONFIRMED_BATTERY_SIGIDS = (
        "230320252,230320459,230320275,230320146,230320463,230320473,"
        "230320462,230320469,230320470,230320108,230320460,230320461,"
        "230320514,230320107,230320265,230320266,230320267,230320148,"
        "230320165,230320181,230320147,230320164,230320180,230320151,"
        "230320168,230320184,230320159,230320174,230320190,230320158,"
        "230320173,230320189,230320446,230320448,230320450,230320447,"
        "230320449,230320451,230320152,230320169,230320185,230320163,"
        "230320179,230320194,230320492,230320493,230320494,230320498,"
        "230320499,230320500"
    )
    base_url: str
    station_dn: str
    username: str
    password: str
    database_path: str

    @classmethod
    def from_environment(cls) -> "Configuration":
        environment_names = {
            "base_url": "HEDP_FUSIONSOLAR_BASE_URL",
            "station_dn": "HEDP_FUSIONSOLAR_STATION_DN",
            "username": "HEDP_FUSIONSOLAR_USERNAME",
            "password": "HEDP_FUSIONSOLAR_PASSWORD",
            "database_path": "HEDP_DATABASE_PATH",
        }
        values = {
            field: os.environ.get(environment_name)
            for field, environment_name in environment_names.items()
        }
        missing = [
            environment_names[field]
            for field, value in values.items()
            if value is None or value == ""
        ]
        if missing:
            raise RuntimeError(
                f"Missing required environment variables: {', '.join(missing)}"
            )
        return cls(**values)

    @staticmethod
    def device_dns_from_environment() -> list[str]:
        value = os.environ.get("HEDP_FUSIONSOLAR_DEVICE_DNS")
        if value is None or not value.strip():
            raise RuntimeError(
                "Missing required environment variable: "
                "HEDP_FUSIONSOLAR_DEVICE_DNS"
            )
        return list(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))

    @staticmethod
    def database_path_from_environment() -> str:
        value = os.environ.get("HEDP_DATABASE_PATH", "").strip()
        if not value:
            raise RuntimeError(
                "Missing required environment variable: HEDP_DATABASE_PATH"
            )
        return value

    @staticmethod
    def battery_dc_from_environment() -> tuple[str, str]:
        device_dn = os.environ.get(
            "HEDP_FUSIONSOLAR_BATTERY_DN",
            Configuration.CONFIRMED_BATTERY_DEVICE_DN,
        ).strip()
        sigids = os.environ.get(
            "HEDP_FUSIONSOLAR_BATTERY_SIGIDS",
            Configuration.CONFIRMED_BATTERY_SIGIDS,
        ).strip()
        if not device_dn:
            device_dn = Configuration.CONFIRMED_BATTERY_DEVICE_DN
        if not sigids:
            sigids = Configuration.CONFIRMED_BATTERY_SIGIDS
        return device_dn, sigids
