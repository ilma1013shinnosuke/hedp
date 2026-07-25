from __future__ import annotations

from datetime import datetime, timezone
import logging
import time
from urllib.parse import urlencode

from hedp.adapters.external_errors import normalize_external_error
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
    ) -> tuple[list[RawData], list[tuple[int, dict[str, object]]]]:
        collected = []
        failures = []
        for target_index, device_dn in enumerate(device_dns, start=1):
            try:
                collected.append(self.collect_device(device_dn))
            except Exception as error:
                report = normalize_external_error(error).as_dict()
                logging.error(
                    "device-realtime failed target_index=%s error_type=%s "
                    "category=%s code=%s retryable=%s",
                    target_index,
                    report["error_type"],
                    report["category"],
                    report["code"],
                    report["retryable"],
                )
                failures.append((target_index, report))
        return collected, failures
