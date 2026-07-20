import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Configuration:
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
