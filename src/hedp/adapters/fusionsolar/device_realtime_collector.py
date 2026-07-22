from __future__ import annotations

from datetime import datetime, timezone
import logging
import time
from urllib.parse import urlencode

from hedp.adapters.fusionsolar.client import FusionSolarClient
from hedp.storage import RawData


class FusionSolarDeviceRealtimeCollector:
    ENDPOINT = "/rest/pvms/web/device/v1/device-realtime-data"

    def __init__(self, client: FusionSolarClient) -> None:
        self.client = client

    def collect_device(self, device_dn: str) -> RawData:
        query = urlencode({"deviceDn": device_dn, "_": int(time.time() * 1000)})
        payload = self.client.get_json(f"{self.ENDPOINT}?{query}")
        return RawData(
            source="fusionsolar_device_realtime",
            timestamp=datetime.now(timezone.utc),
            payload=payload,
            metadata={"device_dn": device_dn},
        )

    def collect_devices(
        self, device_dns: list[str]
    ) -> tuple[list[RawData], list[tuple[str, str]]]:
        collected = []
        failures = []
        for device_dn in device_dns:
            try:
                collected.append(self.collect_device(device_dn))
            except Exception as error:
                summary = f"{type(error).__name__}: {error}"
                logging.error("device-realtime failed for %s: %s", device_dn, summary)
                failures.append((device_dn, summary))
        return collected, failures
