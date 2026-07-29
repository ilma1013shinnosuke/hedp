from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from hedp.adapters.fusionsolar.energy_aggregation import (
    build_daily_energy_summary,
    daily_summary_records,
)
from hedp.observations import Quality
from hedp.storage import Record


def _records(day: date, *, missing_interval: int | None = None) -> list[Record]:
    midnight = datetime(
        day.year,
        day.month,
        day.day,
        tzinfo=ZoneInfo("Asia/Tokyo"),
    ).astimezone(timezone.utc)
    daily = {
        "totalProductPower": 40,
        "totalSelfUsePower": 12,
        "totalOnGridPower": 28,
        "totalBuyPower": 6,
        "totalUsePower": 18,
    }
    records = [
        Record("fusionsolar_energy_balance", midnight, metric, value, "unknown")
        for metric, value in daily.items()
    ]
    records.extend(
        Record(
            "fusionsolar_energy_balance",
            midnight + timedelta(minutes=index * 5),
            "qualifiedGridImportPower",
            None if index == missing_interval else 1.2,
            "kW",
        )
        for index in range(288)
    )
    return records


def test_daily_api_totals_are_authoritative_and_profile_is_integrated() -> None:
    summary = build_daily_energy_summary(
        _records(date(2026, 7, 1)),
        date(2026, 7, 1),
        validated_grid_import_metric="qualifiedGridImportPower",
    )

    assert summary.grid_import_kwh == Decimal("6")
    assert summary.daily_totals_quality == Quality.GOOD
    assert summary.interval_coverage == Decimal(1)
    assert sum(
        interval.grid_import_kwh
        for interval in summary.five_minute_grid_import
        if interval.grid_import_kwh is not None
    ) == Decimal("28.80000000000000000000000000")


def test_missing_interval_is_not_zero_filled() -> None:
    summary = build_daily_energy_summary(
        _records(date(2026, 7, 1), missing_interval=10),
        date(2026, 7, 1),
        validated_grid_import_metric="qualifiedGridImportPower",
    )

    assert summary.grid_import_kwh == Decimal("6")
    assert summary.interval_quality == Quality.MISSING
    assert summary.interval_coverage == Decimal(287) / Decimal(288)
    assert summary.five_minute_grid_import[10].grid_import_kwh is None


def test_unqualified_profile_metric_is_not_guessed() -> None:
    summary = build_daily_energy_summary(
        _records(date(2026, 7, 1)),
        date(2026, 7, 1),
    )

    assert summary.daily_totals_quality == Quality.GOOD
    assert summary.five_minute_grid_import == ()
    assert summary.interval_quality == Quality.UNKNOWN
    assert "daily_interval_coverage_ratio" not in {
        record.metric for record in daily_summary_records(summary)
    }


def test_exact_daily_totals_convert_to_normal_retained_records() -> None:
    summary = build_daily_energy_summary(
        _records(date(2026, 7, 1)),
        date(2026, 7, 1),
        validated_grid_import_metric="qualifiedGridImportPower",
    )

    records = daily_summary_records(summary)
    by_metric = {record.metric: record for record in records}

    assert by_metric["daily_generation_kwh"].value == 40.0
    assert by_metric["daily_grid_import_kwh"].value == 6.0
    assert by_metric["daily_consumption_kwh"].value == 18.0
    assert by_metric["daily_interval_coverage_ratio"].value == 1.0
    assert all(record.source == "fusionsolar_energy_daily_summary" for record in records)
    assert all(record.timestamp.tzinfo is not None for record in records)
