from __future__ import annotations

from datetime import date, datetime, time, timezone
import json
import logging
from datetime import timedelta
from zoneinfo import ZoneInfo

from hedp.adapters.fusionsolar.client import FusionSolarClient
from hedp.storage import RawData


class FusionSolarAlarmCollector:
    ENDPOINT = "/rest/pvms/fm/v1/query"
    MAX_PAGES = 1000

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
        results = []
        target_date = start_date
        tokyo = ZoneInfo("Asia/Tokyo")
        while target_date <= end_date:
            begin = datetime.combine(target_date, time.min, tokyo)
            end = datetime.combine(target_date, time(23, 59, 59), tokyo)
            results.extend(
                self._collect_pages(
                    "HISTORY",
                    device_dn,
                    {
                        "begin": int(begin.timestamp() * 1000),
                        "end": int(end.timestamp() * 1000),
                    },
                    target_date,
                )
            )
            target_date += timedelta(days=1)
        return results

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
        target_date: date | None = None,
    ) -> list[RawData]:
        results = []
        page_number = 1
        seen_pages = set()
        collected_hits = 0
        collection_id = (
            datetime.now(timezone.utc).isoformat()
            if data_type == "CURRENT"
            else ":".join(
                (
                    data_type,
                    device_dn,
                    target_date.isoformat() if target_date else "",
                    str(occur_utc.get("begin")) if occur_utc else "",
                    str(occur_utc.get("end")) if occur_utc else "",
                )
            )
        )
        while True:
            if page_number > self.MAX_PAGES:
                raise RuntimeError("Alarm pagination exceeded maximum pages")
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
            fingerprint = json.dumps(
                payload, sort_keys=True, separators=(",", ":")
            )
            if fingerprint in seen_pages:
                raise RuntimeError("Alarm pagination repeated page content")
            seen_pages.add(fingerprint)
            results.append(
                RawData(
                    source=f"fusionsolar_alarm_{data_type.lower()}",
                    timestamp=datetime.now(timezone.utc),
                    payload=payload,
                    metadata={
                        "device_dn": device_dn,
                        "collection_id": collection_id,
                        "data_type": data_type,
                        "page_no": page_number,
                        "page_size": self.page_size,
                        "target_date": (
                            target_date.isoformat() if target_date else None
                        ),
                        "begin": occur_utc.get("begin") if occur_utc else None,
                        "end": occur_utc.get("end") if occur_utc else None,
                    },
                )
            )
            hits_count = self._hits_count(payload)
            collected_hits += hits_count
            if self._is_last_page(
                payload, page_number, hits_count, collected_hits
            ):
                return results
            page_number += 1

    def _hits_count(self, payload: object) -> int:
        if not isinstance(payload, dict):
            return 0
        data = payload.get("data")
        if not isinstance(data, dict):
            return 0
        hits = data.get("hits")
        return len(hits) if isinstance(hits, list) else 0

    def _is_last_page(
        self,
        payload: object,
        page_number: int,
        hits_count: int,
        collected_hits: int,
    ) -> bool:
        if not isinstance(payload, dict):
            return True
        data = payload.get("data")
        if not isinstance(data, dict):
            return True
        if hits_count == 0:
            return True
        total_count = data.get("totalCount")
        if isinstance(total_count, int) and collected_hits >= total_count:
            return True
        group_result = data.get("groupResult")
        if isinstance(group_result, dict):
            total_pages = group_result.get("totalPage")
            if isinstance(total_pages, int) and page_number >= total_pages:
                return True
        offset = data.get("offset")
        limit = data.get("limit")
        if (
            isinstance(total_count, int)
            and isinstance(offset, int)
            and isinstance(limit, int)
            and offset >= 0
            and offset + max(limit, hits_count) >= total_count
        ):
            return True
        return hits_count < self.page_size
