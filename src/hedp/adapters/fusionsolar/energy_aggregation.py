"""Lightweight derived energy summaries from FusionSolar energy-balance Records.

Daily totals returned by FusionSolar are kept as the authoritative daily facts.
Five-minute power samples are integrated separately for time-of-use analysis and
never silently substituted for a missing daily total.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from hedp.observations import Quality
from hedp.storage import Record


FIVE_MINUTE_HOURS = Decimal(5) / Decimal(60)
DAILY_METRICS = {
    "generation_kwh": "totalProductPower",
    "self_consumption_kwh": "totalSelfUsePower",
    "grid_export_kwh": "totalOnGridPower",
    "grid_import_kwh": "totalBuyPower",
    "consumption_kwh": "totalUsePower",
}


@dataclass(frozen=True)
class FiveMinuteEnergy:
    started_at: datetime
    grid_import_kwh: Decimal | None
    quality: Quality
    reason: str | None = None


@dataclass(frozen=True)
class DailyEnergySummary:
    day: date
    generation_kwh: Decimal | None
    self_consumption_kwh: Decimal | None
    grid_export_kwh: Decimal | None
    grid_import_kwh: Decimal | None
    consumption_kwh: Decimal | None
    daily_totals_quality: Quality
    five_minute_grid_import: tuple[FiveMinuteEnergy, ...]
    interval_coverage: Decimal
    interval_quality: Quality
    source: str


def build_daily_energy_summary(
    records: list[Record],
    day: date,
    *,
    timezone_name: str = "Asia/Tokyo",
    validated_grid_import_metric: str | None = None,
) -> DailyEnergySummary:
    """Build a daily fact plus an optional time-of-use profile.

    ``validated_grid_import_metric`` must only be supplied after its meaning and
    unit have been qualified. Current FusionSolar raw keys are intentionally not
    guessed here.
    """

    timezone = ZoneInfo(timezone_name)
    day_records = [
        record
        for record in records
        if record.timestamp.astimezone(timezone).date() == day
    ]
    daily_values: dict[str, Decimal | None] = {}
    for field, metric in DAILY_METRICS.items():
        matches = [record for record in day_records if record.metric == metric]
        values = {
            Decimal(str(record.value))
            for record in matches
            if record.value is not None
        }
        if len(values) > 1:
            raise ValueError(f"conflicting daily values for {metric}")
        daily_values[field] = next(iter(values), None)

    present_count = sum(value is not None for value in daily_values.values())
    if present_count == len(DAILY_METRICS):
        daily_quality = Quality.GOOD
    elif present_count:
        daily_quality = Quality.MISSING
    else:
        daily_quality = Quality.MISSING

    intervals: list[FiveMinuteEnergy] = []
    if validated_grid_import_metric is not None:
        samples_by_timestamp = {
            record.timestamp: record
            for record in day_records
            if record.metric == validated_grid_import_metric
        }
        for index in range(288):
            local_start = datetime.combine(
                day,
                datetime.min.time(),
                timezone,
            ).replace(
                hour=(index * 5) // 60,
                minute=(index * 5) % 60,
            )
            timestamp = local_start.astimezone(ZoneInfo("UTC"))
            sample = samples_by_timestamp.get(timestamp)
            if sample is None or sample.value is None:
                intervals.append(
                    FiveMinuteEnergy(
                        started_at=timestamp,
                        grid_import_kwh=None,
                        quality=Quality.MISSING,
                        reason="five_minute_grid_import_missing",
                    )
                )
                continue
            power_kw = Decimal(str(sample.value))
            if power_kw < 0:
                intervals.append(
                    FiveMinuteEnergy(
                        started_at=timestamp,
                        grid_import_kwh=None,
                        quality=Quality.INVALID,
                        reason="negative_grid_import_power",
                    )
                )
                continue
            intervals.append(
                FiveMinuteEnergy(
                    started_at=timestamp,
                    grid_import_kwh=power_kw * FIVE_MINUTE_HOURS,
                    quality=Quality.GOOD,
                )
            )

    good_intervals = sum(
        interval.quality == Quality.GOOD for interval in intervals
    )
    interval_coverage = (
        Decimal(good_intervals) / Decimal(288) if intervals else Decimal(0)
    )
    if not intervals:
        interval_quality = Quality.UNKNOWN
    elif good_intervals == 288:
        interval_quality = Quality.GOOD
    elif good_intervals:
        interval_quality = Quality.MISSING
    else:
        interval_quality = Quality.MISSING

    return DailyEnergySummary(
        day=day,
        generation_kwh=daily_values["generation_kwh"],
        self_consumption_kwh=daily_values["self_consumption_kwh"],
        grid_export_kwh=daily_values["grid_export_kwh"],
        grid_import_kwh=daily_values["grid_import_kwh"],
        consumption_kwh=daily_values["consumption_kwh"],
        daily_totals_quality=daily_quality,
        five_minute_grid_import=tuple(intervals),
        interval_coverage=interval_coverage,
        interval_quality=interval_quality,
        source="fusionsolar_energy_balance",
    )


def daily_summary_records(
    summary: DailyEnergySummary,
    *,
    timezone_name: str = "Asia/Tokyo",
) -> list[Record]:
    """Convert a daily summary into the repository's normal retained records.

    Exact FusionSolar daily totals are written as derived facts. Missing values
    remain absent rather than being replaced with zero. The five-minute profile
    stays separate and is represented here only by its coverage ratio.
    """

    timezone = ZoneInfo(timezone_name)
    timestamp = datetime.combine(
        summary.day,
        datetime.min.time(),
        timezone,
    ).astimezone(ZoneInfo("UTC"))
    values = {
        "daily_generation_kwh": summary.generation_kwh,
        "daily_self_consumption_kwh": summary.self_consumption_kwh,
        "daily_grid_export_kwh": summary.grid_export_kwh,
        "daily_grid_import_kwh": summary.grid_import_kwh,
        "daily_consumption_kwh": summary.consumption_kwh,
    }
    records = [
        Record(
            source="fusionsolar_energy_daily_summary",
            timestamp=timestamp,
            metric=metric,
            value=float(value),
            unit="kWh",
        )
        for metric, value in values.items()
        if value is not None
    ]
    if summary.five_minute_grid_import:
        records.append(
            Record(
                source="fusionsolar_energy_daily_summary",
                timestamp=timestamp,
                metric="daily_interval_coverage_ratio",
                value=float(summary.interval_coverage),
                unit="ratio",
            )
        )
    return records
