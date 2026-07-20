from __future__ import annotations

from datetime import date, datetime, time, timezone
import logging
from zoneinfo import ZoneInfo

from hedp.fusionsolar_client import FusionSolarClient
from hedp.raw_data import RawData


class FusionSolarAlarmCollector:
    ENDPOINT = "/rest/pvms/fm/v1/query"

    def __init__(self, client: FusionSolarClient, page_size: int = 10) -> None:
        self.client = client
        self.page_size = page_size

    def collect_current_device(self, device_dn: str) -> list[RawData]:
        return self._collect_pages("CURRENT", device_dn)

    def collect_history_device(
        self, device_dn: str, start_date: date, end_date: date
    ) -> list[RawData]:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        tokyo = ZoneInfo("Asia/Tokyo")
        begin = datetime.combine(start_date, time.min, tokyo)
        end = datetime.combine(end_date, time(23, 59, 59), tokyo)
        return self._collect_pages(
            "HISTORY",
            device_dn,
            {
                "begin": int(begin.timestamp() * 1000),
                "end": int(end.timestamp() * 1000),
            },
            start_date,
            end_date,
        )

    def collect_current_devices(
        self, device_dns: list[str]
    ) -> tuple[list[RawData], list[tuple[str, str]]]:
        return self._collect_devices(device_dns, "CURRENT")

    def collect_history_devices(
        self, device_dns: list[str], start_date: date, end_date: date
    ) -> tuple[list[RawData], list[tuple[str, str]]]:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        return self._collect_devices(
            device_dns, "HISTORY", start_date, end_date
        )

    def _collect_devices(
        self,
        device_dns: list[str],
        data_type: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> tuple[list[RawData], list[tuple[str, str]]]:
        collected = []
        failures = []
        for device_dn in device_dns:
            try:
                if data_type == "CURRENT":
                    collected.extend(self.collect_current_device(device_dn))
                else:
                    assert start_date is not None and end_date is not None
                    collected.extend(
                        self.collect_history_device(
                            device_dn, start_date, end_date
                        )
                    )
            except Exception as error:
                summary = f"{type(error).__name__}: {error}"
                logging.error(
                    "alarm %s failed for %s: %s",
                    data_type.lower(),
                    device_dn,
                    summary,
                )
                failures.append((device_dn, summary))
        return collected, failures

    def _collect_pages(
        self,
        data_type: str,
        device_dn: str,
        occur_utc: dict[str, int] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[RawData]:
        results = []
        page_number = 1
        while True:
            request: dict[str, object] = {
                "dataType": data_type,
                "domainType": "SOLAR",
                "pageNo": page_number,
                "pageSize": self.page_size,
                "nativeMoDn": [device_dn],
            }
            if occur_utc is not None:
                request["occurUTC"] = occur_utc
            payload = self.client.post_json(self.ENDPOINT, request)
            results.append(
                RawData(
                    source=f"fusionsolar_alarm_{data_type.lower()}",
                    timestamp=datetime.now(timezone.utc),
                    payload=payload,
                    metadata={
                        "device_dn": device_dn,
                        "page_number": page_number,
                        "start_date": (
                            start_date.isoformat() if start_date else None
                        ),
                        "end_date": end_date.isoformat() if end_date else None,
                    },
                )
            )
            if self._is_last_page(payload, page_number):
                return results
            page_number += 1

    def _is_last_page(self, payload: object, page_number: int) -> bool:
        if not isinstance(payload, dict):
            return True
        data = payload.get("data")
        if not isinstance(data, dict):
            return True
        total_count = data.get("totalCount")
        if not isinstance(total_count, int):
            return True
        return page_number * self.page_size >= total_count
