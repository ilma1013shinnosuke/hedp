import json
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from hedp.intelligence.solar_self_consumption_opportunity import (
    ExplanationOutcome,
    explain_previous_day_solar_self_consumption_opportunity,
)
from hedp.storage import RawData


EVALUATED_AT = datetime(2026, 7, 25, 3, 0, tzinfo=timezone.utc)
TARGET_DATE = date(2026, 7, 24)
FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "fusionsolar"
    / "energy_balance_opportunity_anonymous.json"
)


def energy_balance_raw(**changes: object) -> RawData:
    payload = json.loads(FIXTURE.read_text())
    start = datetime.combine(TARGET_DATE, datetime.min.time())
    axis = [
        (start + timedelta(minutes=5 * index)).strftime("%Y-%m-%d %H:%M")
        for index in range(288)
    ]
    payload["data"].update(
        {
            "xAxis": axis,
            "productPower": ["2.0"] * 288,
            "selfUsePower": ["1.0"] * 288,
            "onGridPower": ["1.0"] * 288,
        }
    )
    values: dict[str, object] = {
        "source": "fusionsolar_energy_balance",
        "timestamp": EVALUATED_AT - timedelta(hours=1),
        "payload": payload,
        "target_date": TARGET_DATE,
    }
    values.update(changes)
    return RawData(**values)


def test_explains_observed_opportunity_without_mutating_anonymous_raw_data() -> None:
    raw = energy_balance_raw()
    before = deepcopy(raw.payload)

    result = explain_previous_day_solar_self_consumption_opportunity(
        raw, evaluated_at=EVALUATED_AT
    )

    assert result.outcome is ExplanationOutcome.EXPLAIN
    assert result.reason_code == "reported_surplus_with_grid_export_context"
    assert result.reported_context_intervals == 288
    assert "金額効果は算出できません" in result.summary
    assert "機器操作と快適性の変更は行っていません" in result.summary
    assert raw.payload == before


def test_reports_no_opportunity_when_the_conservative_rule_is_not_met() -> None:
    raw = energy_balance_raw()
    raw.payload["data"]["totalSelfUsePower"] = "10.0"

    result = explain_previous_day_solar_self_consumption_opportunity(
        raw, evaluated_at=EVALUATED_AT
    )

    assert result.outcome is ExplanationOutcome.NO_OPPORTUNITY_OBSERVED
    assert result.reason_code == "no_reported_surplus_with_grid_export_context"


def test_requires_at_least_six_five_minute_context_intervals() -> None:
    raw = energy_balance_raw()
    raw.payload["data"]["productPower"] = ["1.0"] * 283 + ["2.0"] * 5
    raw.payload["data"]["selfUsePower"] = ["1.0"] * 288
    raw.payload["data"]["onGridPower"] = ["0.0"] * 283 + ["1.0"] * 5

    result = explain_previous_day_solar_self_consumption_opportunity(
        raw, evaluated_at=EVALUATED_AT
    )

    assert result.outcome is ExplanationOutcome.NO_OPPORTUNITY_OBSERVED
    assert result.reported_context_intervals == 5


@pytest.mark.parametrize(
    ("changes", "reason_code"),
    [
        ({"target_date": date(2026, 7, 23)}, "not_previous_completed_jst_day"),
        (
            {"timestamp": EVALUATED_AT - timedelta(hours=36, seconds=1)},
            "observation_stale",
        ),
    ],
)
def test_declines_input_that_is_not_a_fresh_completed_previous_jst_day(
    changes: dict[str, object], reason_code: str
) -> None:
    result = explain_previous_day_solar_self_consumption_opportunity(
        energy_balance_raw(**changes), evaluated_at=EVALUATED_AT
    )

    assert result.outcome is ExplanationOutcome.NO_DECISION
    assert result.reason_code == reason_code


@pytest.mark.parametrize(
    ("mutate", "reason_code"),
    [
        (
            lambda data: data["xAxis"].pop(),
            "x_axis_incomplete_or_invalid",
        ),
        (
            lambda data: data["selfUsePower"].__setitem__(10, "--"),
            "required_series_missing_or_nonfinite",
        ),
        (
            lambda data: data.__setitem__("totalOnGridPower", "NaN"),
            "required_totals_missing_or_nonfinite",
        ),
    ],
)
def test_declines_incomplete_or_nonfinite_vendor_data(
    mutate: object, reason_code: str
) -> None:
    raw = energy_balance_raw()
    mutate(raw.payload["data"])

    result = explain_previous_day_solar_self_consumption_opportunity(
        raw, evaluated_at=EVALUATED_AT
    )

    assert result.outcome is ExplanationOutcome.NO_DECISION
    assert result.reason_code == reason_code


def test_safe_output_is_bounded_and_excludes_raw_arrays_and_identifiers() -> None:
    raw = energy_balance_raw()
    result = explain_previous_day_solar_self_consumption_opportunity(
        raw, evaluated_at=EVALUATED_AT
    )

    payload = result.safe_to_dict()
    encoded = json.dumps(payload).encode("utf-8")

    assert len(encoded) <= 4 * 1024
    assert all(not isinstance(value, (list, dict)) for value in payload.values())
    assert "source" not in payload
    assert "payload" not in payload


def test_requires_timezone_aware_evaluation_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        explain_previous_day_solar_self_consumption_opportunity(
            energy_balance_raw(), evaluated_at=datetime(2026, 7, 25, 3, 0)
        )
