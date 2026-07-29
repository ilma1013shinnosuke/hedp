from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from hedp.intelligence.electricity_plan_review import (
    MonthlyUsageProfile,
    PlanCostDefinition,
    ReviewKind,
    ReviewPolicy,
    Tier,
    TimeBand,
    due_review_kind,
    monthly_usage_records,
    review_plans,
)
from hedp.observations import Quality


def _flat(plan_id: str, rate: str, *, enrollable: bool = True) -> PlanCostDefinition:
    return PlanCostDefinition(
        plan_id=plan_id,
        display_name=plan_id,
        monthly_basic_charge_yen=Decimal("1000"),
        tiers=(Tier(None, Decimal(rate)),),
        enrollable=enrollable,
        source_ids=("official-rate-revision",),
    )


def _tou() -> PlanCostDefinition:
    return PlanCostDefinition(
        plan_id="tou",
        display_name="tou",
        monthly_basic_charge_yen=Decimal("1000"),
        time_bands=(
            TimeBand("day", time(8), time(22), Decimal("40")),
            TimeBand("night", time(22), time(8), Decimal("20")),
        ),
        source_ids=("official-rate-revision",),
    )


def _month(year: int, month: int, *, night: bool = True) -> MonthlyUsageProfile:
    hour = 23 if night else 12
    start = datetime(year, month, 1, hour, tzinfo=timezone.utc)
    intervals = tuple(
        (start + timedelta(minutes=5 * index), Decimal("1"))
        for index in range(100)
    )
    return MonthlyUsageProfile(
        year=year,
        month=month,
        total_grid_import_kwh=Decimal("100"),
        intervals=intervals,
        interval_coverage=Decimal(1),
        quality=Quality.GOOD,
    )


def test_due_policy_prefers_tariff_change_then_annual_then_semiannual() -> None:
    today = date(2026, 7, 29)

    assert due_review_kind(
        today=today,
        last_semiannual_review=date(2026, 6, 1),
        last_annual_review=date(2026, 6, 1),
        tariff_changed=True,
    ) == ReviewKind.TARIFF_CHANGE
    assert due_review_kind(
        today=today,
        last_semiannual_review=date(2026, 6, 1),
        last_annual_review=date(2025, 7, 1),
        tariff_changed=False,
    ) == ReviewKind.ANNUAL
    assert due_review_kind(
        today=today,
        last_semiannual_review=date(2026, 1, 1),
        last_annual_review=date(2026, 1, 1),
        tariff_changed=False,
    ) == ReviewKind.SEMIANNUAL


def test_review_uses_time_distribution_and_never_changes_contract() -> None:
    usage = [_month(2025 + index // 12, index % 12 + 1) for index in range(12)]

    result = review_plans(
        kind=ReviewKind.SEMIANNUAL,
        evaluated_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
        current_plan_id="flat",
        plans=[_flat("flat", "35"), _tou()],
        usage=usage,
    )

    assert result.quality == Quality.GOOD
    assert result.recommended_plan_id == "tou"
    assert result.estimated_savings_yen == Decimal("18000")
    assert result.automatic_contract_change is False


def test_incomplete_profile_blocks_time_of_use_recommendation() -> None:
    incomplete = MonthlyUsageProfile(
        year=2026,
        month=1,
        total_grid_import_kwh=Decimal("100"),
        intervals=(),
        interval_coverage=Decimal("0.5"),
        quality=Quality.MISSING,
    )

    result = review_plans(
        kind=ReviewKind.SEMIANNUAL,
        evaluated_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
        current_plan_id="tou",
        plans=[_tou(), _flat("flat", "35")],
        usage=[incomplete] * 12,
        policy=ReviewPolicy(minimum_months=12),
    )

    assert result.quality == Quality.MISSING
    assert result.recommended_plan_id is None


def test_closed_current_plan_is_baseline_but_not_new_candidate() -> None:
    usage = [_month(2025 + index // 12, index % 12 + 1) for index in range(12)]

    result = review_plans(
        kind=ReviewKind.ANNUAL,
        evaluated_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
        current_plan_id="legacy",
        plans=[_flat("legacy", "20", enrollable=False), _flat("open", "30")],
        usage=usage,
    )

    assert result.current_plan_cost_yen == Decimal("36000")
    assert result.recommended_plan_id == "legacy"
    assert result.estimated_savings_yen == Decimal("0")


def test_monthly_profile_converts_to_normal_retained_records() -> None:
    records = monthly_usage_records(_month(2026, 7))
    by_metric = {record.metric: record for record in records}

    assert by_metric["monthly_grid_import_kwh"].value == 100.0
    assert by_metric["monthly_interval_coverage_ratio"].value == 1.0
    assert by_metric["monthly_interval_count"].value == 100
    assert all(
        record.source == "fusionsolar_energy_monthly_summary" for record in records
    )
