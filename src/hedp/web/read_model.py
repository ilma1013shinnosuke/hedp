"""Read-only projection of stored HESTIA facts for the local dashboard."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from hedp.storage import Record, Storage


_SOURCE_PRIORITY = (
    "fusionsolar_modbus_tcp",
    "fusionsolar_energy_balance",
    "fusionsolar",
)
_SOLAR_METRICS = ("input_power", "productPower")
_BATTERY_METRICS = ("storage_soc",)
_TODAY_METRICS = ("daily_yield", "totalProductPower")
_SELF_CONSUMPTION_METRICS = (
    "selfUsePowerRatioByProduct",
    "daily_self_consumption_percent",
)


def read_only_dashboard_snapshot_provider(
    database_path: str | Path,
    *,
    clock: Callable[[], datetime] | None = None,
    timezone_name: str = "Asia/Tokyo",
    stale_after: timedelta = timedelta(minutes=15),
) -> Callable[[], dict[str, Any]]:
    """Build a callable that projects the database without ever writing it."""

    path = str(database_path)
    current_time = clock or (lambda: datetime.now(timezone.utc))

    def provide() -> dict[str, Any]:
        return build_read_only_dashboard_snapshot(
            path,
            at=current_time(),
            timezone_name=timezone_name,
            stale_after=stale_after,
        )

    return provide


def build_read_only_dashboard_snapshot(
    database_path: str | Path,
    *,
    at: datetime | None = None,
    timezone_name: str = "Asia/Tokyo",
    stale_after: timedelta = timedelta(minutes=15),
) -> dict[str, Any]:
    """Return a compact, anonymous view of confirmed stored metrics."""

    now = _as_aware(at or datetime.now(timezone.utc))
    local_timezone = ZoneInfo(timezone_name)
    local_now = now.astimezone(local_timezone)
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = local_start.astimezone(timezone.utc)
    end = now.astimezone(timezone.utc)

    storage = Storage(str(database_path))
    connection = storage.connect_readonly()
    try:
        records = [
            record
            for source in _SOURCE_PRIORITY
            for record in storage.load_records_for_source_window(source, start, end)
        ]
    finally:
        connection.close()

    solar_record = _latest_by_priority(records, _SOLAR_METRICS)
    battery_record = _latest_by_priority(records, _BATTERY_METRICS)
    today_record = _latest_by_priority(records, _TODAY_METRICS)
    self_consumption_record = _latest_by_priority(
        records, _SELF_CONSUMPTION_METRICS
    )
    observed_records = [
        record
        for record in (
            solar_record,
            battery_record,
            today_record,
            self_consumption_record,
        )
        if record is not None
    ]
    observed_at = max(
        (_as_aware(record.timestamp) for record in observed_records),
        default=None,
    )
    quality = _quality(observed_at, now, stale_after)

    return {
        "schema": "hestia.interface.summary.v1",
        "mode": "live_read_only",
        "observed_at": observed_at.isoformat() if observed_at else None,
        "quality": quality,
        "home": {"status": "unknown", "alerts": None},
        "energy": {
            "solar_kw": _numeric_value(solar_record),
            "home_kw": None,
            "battery_percent": _numeric_value(battery_record),
            "grid_kw": None,
            "today_kwh": _numeric_value(today_record),
            "self_consumption_percent": _numeric_value(
                self_consumption_record
            ),
            "history": _solar_history(records, local_timezone),
        },
        "climate": {
            "temperature_c": None,
            "humidity_percent": None,
            "co2_ppm": None,
        },
        "devices": [],
    }


def unavailable_dashboard_snapshot() -> dict[str, Any]:
    """Return a non-sensitive response when the read model is unavailable."""

    return {
        "schema": "hestia.interface.summary.v1",
        "mode": "unavailable",
        "observed_at": None,
        "quality": {
            "status": "missing",
            "reason": "read_model_unavailable",
        },
        "home": {"status": "unknown", "alerts": None},
        "energy": {
            "solar_kw": None,
            "home_kw": None,
            "battery_percent": None,
            "grid_kw": None,
            "today_kwh": None,
            "self_consumption_percent": None,
            "history": [],
        },
        "climate": {
            "temperature_c": None,
            "humidity_percent": None,
            "co2_ppm": None,
        },
        "devices": [],
    }


def _latest_by_priority(
    records: Iterable[Record], metrics: tuple[str, ...]
) -> Record | None:
    candidates = [
        record
        for record in records
        if record.metric in metrics and _numeric_value(record) is not None
    ]
    if not candidates:
        return None
    source_rank = {source: index for index, source in enumerate(_SOURCE_PRIORITY)}
    metric_rank = {metric: index for index, metric in enumerate(metrics)}
    return min(
        candidates,
        key=lambda record: (
            source_rank.get(record.source, len(source_rank)),
            metric_rank.get(record.metric, len(metric_rank)),
            -_as_aware(record.timestamp).timestamp(),
        ),
    )


def _solar_history(
    records: Iterable[Record], local_timezone: ZoneInfo
) -> list[dict[str, Any]]:
    for source, metric in (
        ("fusionsolar_modbus_tcp", "input_power"),
        ("fusionsolar_energy_balance", "productPower"),
        ("fusionsolar", "productPower"),
    ):
        matching = [
            record
            for record in records
            if record.source == source
            and record.metric == metric
            and _numeric_value(record) is not None
        ]
        if matching:
            ordered = sorted(
                matching,
                key=lambda record: _as_aware(record.timestamp),
            )
            return [
                {
                    "time": _as_aware(record.timestamp)
                    .astimezone(local_timezone)
                    .strftime("%H:%M"),
                    "solar_kw": _numeric_value(record),
                }
                for record in _downsample(ordered, maximum=144)
            ]
    return []


def _downsample(records: list[Record], *, maximum: int) -> list[Record]:
    if len(records) <= maximum:
        return records
    return [
        records[round(index * (len(records) - 1) / (maximum - 1))]
        for index in range(maximum)
    ]


def _quality(
    observed_at: datetime | None,
    now: datetime,
    stale_after: timedelta,
) -> dict[str, str]:
    if observed_at is None:
        return {"status": "missing", "reason": "no_confirmed_metrics"}
    age = now - _as_aware(observed_at)
    if age < timedelta(minutes=-5):
        return {"status": "invalid", "reason": "timestamp_in_future"}
    if age > stale_after:
        return {"status": "stale", "reason": "observation_too_old"}
    return {"status": "good", "reason": "recent_observation"}


def _numeric_value(record: Record | None) -> int | float | None:
    if record is None or isinstance(record.value, bool):
        return None
    return record.value if isinstance(record.value, (int, float)) else None


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
