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
