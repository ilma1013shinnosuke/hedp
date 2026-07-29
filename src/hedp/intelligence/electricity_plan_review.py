"""Pure calculation for periodic household electricity-plan reviews."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from zoneinfo import ZoneInfo

from hedp.adapters.fusionsolar.energy_aggregation import DailyEnergySummary
from hedp.observations import Quality
from hedp.storage import Record


class ReviewKind(str, Enum):
    SEMIANNUAL = "semiannual"
    ANNUAL = "annual"
    TARIFF_CHANGE = "tariff_change"


@dataclass(frozen=True)
class ReviewPolicy:
    semiannual_months: int = 6
    annual_months: int = 12
    minimum_profile_coverage: Decimal = Decimal("0.95")
    minimum_months: int = 12


@dataclass(frozen=True)
class TimeBand:
    name: str
    starts_at: time
    ends_at: time
    unit_rate_yen_per_kwh: Decimal

    def contains(self, value: time) -> bool:
        if self.starts_at < self.ends_at:
            return self.starts_at <= value < self.ends_at
        return value >= self.starts_at or value < self.ends_at


@dataclass(frozen=True)
class Tier:
    up_to_kwh: Decimal | None
    unit_rate_yen_per_kwh: Decimal


@dataclass(frozen=True)
class PlanCostDefinition:
    plan_id: str
    display_name: str
    monthly_basic_charge_yen: Decimal
    tiers: tuple[Tier, ...] = ()
    time_bands: tuple[TimeBand, ...] = ()
    per_kwh_adjustment_yen: Decimal = Decimal(0)
    monthly_discount_yen: Decimal = Decimal(0)
    enrollable: bool = True
    eligibility_confirmed: bool = True
    effective_from: date | None = None
    effective_until: date | None = None
    source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if bool(self.tiers) == bool(self.time_bands):
            raise ValueError("plan must define exactly one of tiers or time_bands")


@dataclass(frozen=True)
class MonthlyUsageProfile:
    year: int
    month: int
    total_grid_import_kwh: Decimal | None
    intervals: tuple[tuple[datetime, Decimal], ...]
    interval_coverage: Decimal
    quality: Quality


@dataclass(frozen=True)
class PlanEstimate:
    plan_id: str
    display_name: str
    total_yen: Decimal | None
    quality: Quality
    reason: str | None
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class ElectricityPlanReview:
    kind: ReviewKind
    evaluated_at: datetime
    current_plan_id: str
    recommended_plan_id: str | None
    current_plan_cost_yen: Decimal | None
    recommended_plan_cost_yen: Decimal | None
    estimated_savings_yen: Decimal | None
    estimates: tuple[PlanEstimate, ...]
    data_months: int
    minimum_interval_coverage: Decimal
    quality: Quality
    reason: str
    automatic_contract_change: bool = False


def due_review_kind(
    *,
    today: date,
    last_semiannual_review: date | None,
    last_annual_review: date | None,
    tariff_changed: bool,
    policy: ReviewPolicy = ReviewPolicy(),
) -> ReviewKind | None:
    if tariff_changed:
        return ReviewKind.TARIFF_CHANGE
    if last_annual_review is None or _months_between(last_annual_review, today) >= (
        policy.annual_months
    ):
        return ReviewKind.ANNUAL
    if last_semiannual_review is None or _months_between(
        last_semiannual_review, today
    ) >= policy.semiannual_months:
        return ReviewKind.SEMIANNUAL
    return None


def aggregate_monthly_usage(
    daily_summaries: list[DailyEnergySummary],
    *,
    timezone_name: str = "Asia/Tokyo",
) -> list[MonthlyUsageProfile]:
    timezone = ZoneInfo(timezone_name)
    groups: dict[tuple[int, int], list[DailyEnergySummary]] = {}
    for summary in daily_summaries:
        groups.setdefault((summary.day.year, summary.day.month), []).append(summary)

    profiles: list[MonthlyUsageProfile] = []
    for (year, month), summaries in sorted(groups.items()):
        days_in_month = calendar.monthrange(year, month)[1]
        by_day = {summary.day: summary for summary in summaries}
        totals = [
            summary.grid_import_kwh
            for summary in summaries
            if summary.grid_import_kwh is not None
        ]
        all_days_present = len(by_day) == days_in_month and len(totals) == days_in_month
        total = sum(totals, Decimal(0)) if all_days_present else None

        intervals = tuple(
            (
                item.started_at.astimezone(timezone),
                item.grid_import_kwh,
            )
            for summary in summaries
            for item in summary.five_minute_grid_import
            if item.grid_import_kwh is not None and item.quality == Quality.GOOD
        )
        expected_intervals = days_in_month * 288
        coverage = Decimal(len(intervals)) / Decimal(expected_intervals)
        if total is None:
            quality = Quality.MISSING
        elif coverage == Decimal(1):
            quality = Quality.GOOD
        elif coverage > 0:
            quality = Quality.MISSING
        else:
            quality = Quality.UNKNOWN
        profiles.append(
            MonthlyUsageProfile(
                year=year,
                month=month,
                total_grid_import_kwh=total,
                intervals=intervals,
                interval_coverage=coverage,
                quality=quality,
            )
        )
    return profiles


def review_plans(
    *,
    kind: ReviewKind,
    evaluated_at: datetime,
    current_plan_id: str,
    plans: list[PlanCostDefinition],
    usage: list[MonthlyUsageProfile],
    policy: ReviewPolicy = ReviewPolicy(),
) -> ElectricityPlanReview:
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    current = next((plan for plan in plans if plan.plan_id == current_plan_id), None)
    if current is None:
        raise ValueError("current plan definition is required")

    minimum_coverage = min(
        (profile.interval_coverage for profile in usage),
        default=Decimal(0),
    )
    estimates = tuple(_estimate(plan, usage, policy) for plan in plans)
    current_estimate = next(
        estimate for estimate in estimates if estimate.plan_id == current_plan_id
    )
    candidates = [
        estimate
        for estimate, plan in zip(estimates, plans)
        if (
            plan.plan_id == current_plan_id
            or (plan.enrollable and plan.eligibility_confirmed)
        )
        and estimate.quality == Quality.GOOD
        and estimate.total_yen is not None
    ]
    if (
        len(usage) < policy.minimum_months
        or current_estimate.quality != Quality.GOOD
        or current_estimate.total_yen is None
        or not candidates
    ):
        return ElectricityPlanReview(
            kind=kind,
            evaluated_at=evaluated_at,
            current_plan_id=current_plan_id,
            recommended_plan_id=None,
            current_plan_cost_yen=current_estimate.total_yen,
            recommended_plan_cost_yen=None,
            estimated_savings_yen=None,
            estimates=estimates,
            data_months=len(usage),
            minimum_interval_coverage=minimum_coverage,
            quality=Quality.MISSING,
            reason="insufficient_complete_months_or_plan_evidence",
        )

    winner = min(candidates, key=lambda estimate: estimate.total_yen)
    return ElectricityPlanReview(
        kind=kind,
        evaluated_at=evaluated_at,
        current_plan_id=current_plan_id,
        recommended_plan_id=winner.plan_id,
        current_plan_cost_yen=current_estimate.total_yen,
        recommended_plan_cost_yen=winner.total_yen,
        estimated_savings_yen=current_estimate.total_yen - winner.total_yen,
        estimates=estimates,
        data_months=len(usage),
        minimum_interval_coverage=minimum_coverage,
        quality=Quality.GOOD,
        reason="comparison_complete",
    )


def monthly_usage_records(
    profile: MonthlyUsageProfile,
    *,
    timezone_name: str = "Asia/Tokyo",
) -> list[Record]:
    """Convert a monthly profile into lightweight retained analysis records."""

    timestamp = datetime(
        profile.year,
        profile.month,
        1,
        tzinfo=ZoneInfo(timezone_name),
    ).astimezone(ZoneInfo("UTC"))
    records: list[Record] = []
    if profile.total_grid_import_kwh is not None:
        records.append(
            Record(
                source="fusionsolar_energy_monthly_summary",
                timestamp=timestamp,
                metric="monthly_grid_import_kwh",
                value=float(profile.total_grid_import_kwh),
                unit="kWh",
            )
        )
    records.extend(
        [
            Record(
                source="fusionsolar_energy_monthly_summary",
                timestamp=timestamp,
                metric="monthly_interval_coverage_ratio",
                value=float(profile.interval_coverage),
                unit="ratio",
            ),
            Record(
                source="fusionsolar_energy_monthly_summary",
                timestamp=timestamp,
                metric="monthly_interval_count",
                value=len(profile.intervals),
                unit="count",
            ),
        ]
    )
    return records


def _estimate(
    plan: PlanCostDefinition,
    usage: list[MonthlyUsageProfile],
    policy: ReviewPolicy,
) -> PlanEstimate:
    total = Decimal(0)
    for profile in usage:
        month_start = date(profile.year, profile.month, 1)
        if plan.effective_from is not None and month_start < plan.effective_from:
            return _unavailable(plan, "outside_plan_effective_period")
        if plan.effective_until is not None and month_start > plan.effective_until:
            return _unavailable(plan, "outside_plan_effective_period")
        if profile.total_grid_import_kwh is None:
            return _unavailable(plan, "monthly_grid_import_missing")
        if plan.time_bands:
            if profile.interval_coverage < policy.minimum_profile_coverage:
                return _unavailable(plan, "time_of_use_profile_coverage_too_low")
            energy_charge = _time_band_charge(plan, profile)
            if energy_charge is None:
                return _unavailable(plan, "unmatched_time_band")
        else:
            energy_charge = _tier_charge(plan.tiers, profile.total_grid_import_kwh)
        adjusted = (
            energy_charge
            + profile.total_grid_import_kwh * plan.per_kwh_adjustment_yen
        )
        total += max(
            Decimal(0),
            plan.monthly_basic_charge_yen
            + adjusted
            - plan.monthly_discount_yen,
        )
    return PlanEstimate(
        plan_id=plan.plan_id,
        display_name=plan.display_name,
        total_yen=total,
        quality=Quality.GOOD,
        reason=None,
        source_ids=plan.source_ids,
    )


def _tier_charge(tiers: tuple[Tier, ...], usage_kwh: Decimal) -> Decimal:
    charge = Decimal(0)
    previous = Decimal(0)
    remaining = usage_kwh
    for tier in tiers:
        if tier.up_to_kwh is None:
            quantity = remaining
        else:
            quantity = min(remaining, tier.up_to_kwh - previous)
        if quantity > 0:
            charge += quantity * tier.unit_rate_yen_per_kwh
            remaining -= quantity
        if tier.up_to_kwh is not None:
            previous = tier.up_to_kwh
        if remaining <= 0:
            break
    if remaining > 0:
        raise ValueError("tier schedule does not cover all usage")
    return charge


def _time_band_charge(
    plan: PlanCostDefinition,
    profile: MonthlyUsageProfile,
) -> Decimal | None:
    charge = Decimal(0)
    for timestamp, energy_kwh in profile.intervals:
        matching = [band for band in plan.time_bands if band.contains(timestamp.time())]
        if len(matching) != 1:
            return None
        charge += energy_kwh * matching[0].unit_rate_yen_per_kwh
    return charge


def _unavailable(plan: PlanCostDefinition, reason: str) -> PlanEstimate:
    return PlanEstimate(
        plan_id=plan.plan_id,
        display_name=plan.display_name,
        total_yen=None,
        quality=Quality.MISSING,
        reason=reason,
        source_ids=plan.source_ids,
    )


def _months_between(earlier: date, later: date) -> int:
    return (later.year - earlier.year) * 12 + later.month - earlier.month
