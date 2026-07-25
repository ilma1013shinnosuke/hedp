import json
from pathlib import Path

import pytest

from hedp.adapters.miele.normalizer import normalize_washer_dryer


FIXTURE = Path(__file__).parent / "fixtures/miele/washer_dryer_state_v1.json"


def test_normalizes_allowlisted_washer_dryer_fields() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    reading = normalize_washer_dryer(payload)

    assert reading.remaining_minutes == 195
    assert reading.elapsed_minutes == 10
    assert reading.scheduled_start_minutes_of_day == 90
    assert reading.temperature_c == 40
    assert "unknown_future_field" not in reading.safe_payload()


def test_missing_sentinel_is_not_changed_to_zero() -> None:
    payload = {"state": {"temperature": {"value_raw": -32_768}}}

    reading = normalize_washer_dryer(payload)

    assert reading.temperature_c is None
    assert reading.status_code is None


def test_unknown_fields_and_text_are_not_exposed_by_safe_payload() -> None:
    private = "private-appliance-or-account-value"
    payload = {
        "state": {
            "status": {"value_raw": 4, "value_localized": private},
            "ProgramID": {"value_raw": 7},
            "unknown_future_field": {"identifier": private},
        },
        "deviceName": private,
    }

    reading = normalize_washer_dryer(payload)

    assert reading.status_code == 4
    assert reading.program_id == 7
    assert private not in repr(reading)
    assert private not in json.dumps(reading.safe_payload())


def test_boolean_and_non_integer_codes_are_not_coerced() -> None:
    reading = normalize_washer_dryer(
        {
            "state": {
                "status": True,
                "ProgramID": 1.5,
                "programType": {"value_raw": -32_768},
                "spinningSpeed": {"value_raw": 0},
            }
        }
    )

    assert reading.status_code is None
    assert reading.program_id is None
    assert reading.program_type_code is None
    assert reading.spin_speed_rpm == 0


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"state": None},
        {"state": {"remainingTime": [1, 60]}},
    ],
)
def test_invalid_or_missing_values_are_safe(value: object) -> None:
    if not isinstance(value, dict) or not isinstance(value.get("state"), dict):
        with pytest.raises(ValueError):
            normalize_washer_dryer(value)
        return

    assert normalize_washer_dryer(value).remaining_minutes is None
