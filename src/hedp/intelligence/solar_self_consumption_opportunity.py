"""Explain a completed day's reported solar self-consumption opportunity.

This module is deliberately offline and side-effect free.  It accepts one
already-collected FusionSolar energy-balance ``RawData`` object and returns a
small explanation only; it neither creates an intent nor accesses storage,
network, adapters, or devices.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Final
from zoneinfo import ZoneInfo

from hedp.storage import RawData


_TOKYO: Final = ZoneInfo("Asia/Tokyo")
_POINT_COUNT: Final = 288
_POINT_INTERVAL: Final = timedelta(minutes=5)
_MAX_FRESHNESS: Final = timedelta(hours=36)
_MAX_SAFE_SERIALIZED_BYTES: Final = 4 * 1024
_MINIMUM_CONTEXT_INTERVALS: Final = 6
_REQUIRED_SERIES: Final = ("productPower", "selfUsePower", "onGridPower")
_REQUIRED_TOTALS: Final = (
    "totalProductPower",
    "totalSelfUsePower",
    "totalOnGridPower",
)


class ExplanationOutcome(str, Enum):
    """The only outcomes available from this read-only explanation."""

    EXPLAIN = "explain"
    NO_OPPORTUNITY_OBSERVED = "no_opportunity_observed"
    NO_DECISION = "no_decision"


class ExplanationReason(str, Enum):
    """Stable reason codes; never expose a parser or vendor-specific error."""

    NOT_PREVIOUS_COMPLETED_JST_DAY = "not_previous_completed_jst_day"
    UNEXPECTED_ENERGY_BALANCE_SOURCE = "unexpected_energy_balance_source"
    OBSERVATION_TIMESTAMP_INVALID = "observation_timestamp_invalid"
    OBSERVATION_STALE = "observation_stale"
    ENERGY_BALANCE_RESPONSE_UNSUCCESSFUL_OR_INVALID = (
        "energy_balance_response_unsuccessful_or_invalid"
    )
    ENERGY_BALANCE_DATA_INVALID = "energy_balance_data_invalid"
    X_AXIS_INCOMPLETE_OR_INVALID = "x_axis_incomplete_or_invalid"
    REQUIRED_SERIES_MISSING_OR_NONFINITE = "required_series_missing_or_nonfinite"
    REQUIRED_TOTALS_MISSING_OR_NONFINITE = "required_totals_missing_or_nonfinite"
    REPORTED_SURPLUS_WITH_GRID_EXPORT_CONTEXT = (
        "reported_surplus_with_grid_export_context"
    )
    NO_REPORTED_SURPLUS_WITH_GRID_EXPORT_CONTEXT = (
        "no_reported_surplus_with_grid_export_context"
    )


@dataclass(frozen=True)
class SolarSelfConsumptionExplanation:
    """A bounded, identifier-free explanation suitable for later display."""

    outcome: ExplanationOutcome
    reason_code: ExplanationReason
    target_date: date | None
    evaluated_at: datetime
    observation_age_minutes: int | None
    reported_context_intervals: int
    summary: str

    def safe_to_dict(self) -> dict[str, str | int | None]:
        """Return a compact representation with no raw data, arrays, or IDs."""

        payload: dict[str, str | int | None] = {
            "outcome": self.outcome.value,
            "reason_code": self.reason_code.value,
            "target_date": self.target_date.isoformat() if self.target_date else None,
            "evaluated_at": self.evaluated_at.isoformat(),
            "observation_age_minutes": self.observation_age_minutes,
            "reported_context_intervals": self.reported_context_intervals,
            "summary": self.summary,
        }
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode(
            "utf-8"
        )
        if len(encoded) > _MAX_SAFE_SERIALIZED_BYTES:
            raise ValueError("safe explanation exceeds 4 KiB")
        return payload


class SolarSelfConsumptionOpportunityExplainer:
    """Apply one conservative, completed-day explanation rule."""

    def explain(
        self, raw_data: RawData, *, evaluated_at: datetime
    ) -> SolarSelfConsumptionExplanation:
        _require_aware("evaluated_at", evaluated_at)
        expected_date = evaluated_at.astimezone(_TOKYO).date() - timedelta(days=1)
        if raw_data.target_date != expected_date:
            return self._no_decision(
                ExplanationReason.NOT_PREVIOUS_COMPLETED_JST_DAY,
                raw_data.target_date,
                evaluated_at,
                None,
                "判断しません。入力が完了済みの前日JST一日分ではありません。",
            )

        if raw_data.source != "fusionsolar_energy_balance":
            return self._no_decision(
                ExplanationReason.UNEXPECTED_ENERGY_BALANCE_SOURCE,
                raw_data.target_date,
                evaluated_at,
                None,
                "判断しません。入力がFusionSolar energy-balance観測ではありません。",
            )

        age = _observation_age(raw_data.timestamp, evaluated_at)
        if age is None:
            return self._no_decision(
                ExplanationReason.OBSERVATION_TIMESTAMP_INVALID,
                raw_data.target_date,
                evaluated_at,
                None,
                "判断しません。観測時刻が欠損、タイムゾーンなし、又は未来です。",
            )
        age_minutes = int(age.total_seconds() // 60)
        if age > _MAX_FRESHNESS:
            return self._no_decision(
                ExplanationReason.OBSERVATION_STALE,
                raw_data.target_date,
                evaluated_at,
                age_minutes,
                "判断しません。完了日データの取得から36時間を超えています。",
            )

        if not isinstance(raw_data.payload, dict) or raw_data.payload.get("success") is not True:
            return self._no_decision(
                ExplanationReason.ENERGY_BALANCE_RESPONSE_UNSUCCESSFUL_OR_INVALID,
                raw_data.target_date,
                evaluated_at,
                age_minutes,
                "判断しません。energy-balance応答が失敗又は不正です。",
            )
        data = raw_data.payload.get("data")
        if not isinstance(data, dict):
            return self._no_decision(
                ExplanationReason.ENERGY_BALANCE_DATA_INVALID,
                raw_data.target_date,
                evaluated_at,
                age_minutes,
                "判断しません。必要なenergy-balanceデータを取得できません。",
            )
        if not _has_strict_jst_five_minute_axis(data.get("xAxis"), raw_data.target_date):
            return self._no_decision(
                ExplanationReason.X_AXIS_INCOMPLETE_OR_INVALID,
                raw_data.target_date,
                evaluated_at,
                age_minutes,
                "判断しません。対象日に厳密な5分間隔の288点がありません。",
            )

        series = _finite_series(data)
        if series is None:
            return self._no_decision(
                ExplanationReason.REQUIRED_SERIES_MISSING_OR_NONFINITE,
                raw_data.target_date,
                evaluated_at,
                age_minutes,
                "判断しません。必須のメーカー報告系列に欠損又は不正値があります。",
            )
        totals = _finite_totals(data)
        if totals is None:
            return self._no_decision(
                ExplanationReason.REQUIRED_TOTALS_MISSING_OR_NONFINITE,
                raw_data.target_date,
                evaluated_at,
                age_minutes,
                "判断しません。必須のメーカー報告合計に欠損又は不正値があります。",
            )

        context_intervals = sum(
            product > self_use and on_grid > 0
            for product, self_use, on_grid in zip(
                series["productPower"],
                series["selfUsePower"],
                series["onGridPower"],
            )
        )
        observed = (
            totals["totalProductPower"] > totals["totalSelfUsePower"]
            and totals["totalOnGridPower"] > 0
            and context_intervals >= _MINIMUM_CONTEXT_INTERVALS
        )
        if observed:
            return SolarSelfConsumptionExplanation(
                outcome=ExplanationOutcome.EXPLAIN,
                reason_code=ExplanationReason.REPORTED_SURPLUS_WITH_GRID_EXPORT_CONTEXT,
                target_date=raw_data.target_date,
                evaluated_at=evaluated_at,
                observation_age_minutes=age_minutes,
                reported_context_intervals=context_intervals,
                summary=(
                    "メーカー報告値で、発電が自家消費を上回り系統への送り出しとみられる"
                    "状態が合計30分相当観測されました。ただし連続時間とは限らず、"
                    "単位と一部キーの厳密な意味、"
                    "移動可能な負荷、料金根拠がないため金額効果は算出できません。"
                    "機器操作と快適性の変更は行っていません。"
                ),
            )
        return SolarSelfConsumptionExplanation(
            outcome=ExplanationOutcome.NO_OPPORTUNITY_OBSERVED,
            reason_code=ExplanationReason.NO_REPORTED_SURPLUS_WITH_GRID_EXPORT_CONTEXT,
            target_date=raw_data.target_date,
            evaluated_at=evaluated_at,
            observation_age_minutes=age_minutes,
            reported_context_intervals=context_intervals,
            summary=(
                "保守的な合計30分相当の基準では、自家消費を増やせる可能性を示す"
                "十分な報告区間を"
                "確認できませんでした。単位と一部キーの厳密な意味は未確認です。"
                "機器操作と快適性の変更は行っていません。"
            ),
        )

    @staticmethod
    def _no_decision(
        reason_code: ExplanationReason,
        target_date: date | None,
        evaluated_at: datetime,
        observation_age_minutes: int | None,
        summary: str,
    ) -> SolarSelfConsumptionExplanation:
        return SolarSelfConsumptionExplanation(
            outcome=ExplanationOutcome.NO_DECISION,
            reason_code=reason_code,
            target_date=target_date,
            evaluated_at=evaluated_at,
            observation_age_minutes=observation_age_minutes,
            reported_context_intervals=0,
            summary=summary,
        )


def explain_previous_day_solar_self_consumption_opportunity(
    raw_data: RawData, *, evaluated_at: datetime
) -> SolarSelfConsumptionExplanation:
    """Explain one prior JST day without writing, dispatching, or calling adapters."""

    return SolarSelfConsumptionOpportunityExplainer().explain(
        raw_data, evaluated_at=evaluated_at
    )


def _observation_age(timestamp: datetime, evaluated_at: datetime) -> timedelta | None:
    if not isinstance(timestamp, datetime):
        return None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return None
    age = evaluated_at - timestamp
    if age < timedelta(0):
        return None
    return age


def _has_strict_jst_five_minute_axis(value: object, target_date: date) -> bool:
    if not isinstance(value, list) or len(value) != _POINT_COUNT:
        return False
    expected = datetime.combine(target_date, datetime.min.time())
    for item in value:
        if not isinstance(item, str):
            return False
        try:
            parsed = datetime.fromisoformat(item)
        except ValueError:
            return False
        if parsed.tzinfo is not None:
            return False
        if parsed != expected:
            return False
        expected += _POINT_INTERVAL
    return True


def _finite_series(data: dict[str, object]) -> dict[str, tuple[float, ...]] | None:
    result: dict[str, tuple[float, ...]] = {}
    for name in _REQUIRED_SERIES:
        values = data.get(name)
        if not isinstance(values, list) or len(values) != _POINT_COUNT:
            return None
        numbers = tuple(_finite_number(value) for value in values)
        if any(value is None for value in numbers):
            return None
        result[name] = tuple(value for value in numbers if value is not None)
    return result


def _finite_totals(data: dict[str, object]) -> dict[str, float] | None:
    result: dict[str, float] = {}
    for name in _REQUIRED_TOTALS:
        value = _finite_number(data.get(name))
        if value is None:
            return None
        result[name] = value
    return result


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
