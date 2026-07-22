from __future__ import annotations

from datetime import datetime, timezone
import logging
import time
from urllib.parse import urlencode

from hedp.adapters.fusionsolar.client import FusionSolarClient
from hedp.raw_data import RawData


class FusionSolarBatteryDcCollector:
    ENDPOINT = "/rest/pvms/web/device/v1/query-battery-dc"

    def __init__(self, client: FusionSolarClient) -> None:
        self.client = client

    def collect_module(
        self, device_dn: str, sigids: str, module_id: int
    ) -> RawData:
        query = urlencode(
            {
                "dn": device_dn,
                "sigids": sigids,
                "moduleId": module_id,
                "_": int(time.time() * 1000),
            }
        )
        payload = self.client.get_json(f"{self.ENDPOINT}?{query}")
        return RawData(
            source="fusionsolar_battery_dc",
            timestamp=datetime.now(timezone.utc),
            payload=payload,
            metadata={"device_dn": device_dn, "module_id": module_id},
        )

    def collect_modules(
        self, device_dn: str, sigids: str, module_ids: list[int]
    ) -> tuple[list[RawData], list[tuple[int, str]]]:
        collected = []
        failures = []
        for module_id in module_ids:
            try:
                collected.append(
                    self.collect_module(device_dn, sigids, module_id)
                )
            except Exception as error:
                summary = f"{type(error).__name__}: {error}"
                logging.error(
                    "battery-dc failed for moduleId=%s: %s",
                    module_id,
                    summary,
                )
                failures.append((module_id, summary))
        return collected, failures
