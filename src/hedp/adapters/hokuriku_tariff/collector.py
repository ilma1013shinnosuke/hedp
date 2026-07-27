"""Bounded collector shell; concrete HTTP layout handling is intentionally absent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .models import TariffDataset
from .parser import parse_official_payload


class OfficialPayloadFetcher(Protocol):
    def fetch(self, *, timeout_seconds: float, max_bytes: int) -> tuple[str, bytes]: ...


@dataclass(frozen=True)
class CollectionLimits:
    timeout_seconds: float = 10.0
    max_bytes: int = 2_000_000

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.max_bytes <= 0:
            raise ValueError("collection limits must be positive")


class HokurikuTariffCollector:
    """Runs one bounded fetch; scheduling belongs outside the adapter."""

    def __init__(
        self,
        fetcher: OfficialPayloadFetcher,
        *,
        limits: CollectionLimits = CollectionLimits(),
    ) -> None:
        self.fetcher = fetcher
        self.limits = limits

    def collect_once(self, *, fetched_at: datetime) -> TariffDataset:
        source_url, payload = self.fetcher.fetch(
            timeout_seconds=self.limits.timeout_seconds,
            max_bytes=self.limits.max_bytes,
        )
        if len(payload) > self.limits.max_bytes:
            raise ValueError("official payload exceeded configured byte limit")
        return parse_official_payload(
            payload,
            source_url=source_url,
            fetched_at=fetched_at,
        )
