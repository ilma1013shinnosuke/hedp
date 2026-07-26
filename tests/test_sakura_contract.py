from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from hedp.adapters.sakura import (
    ChargingState,
    ClimateState,
    DoorLockState,
    PlugState,
    SakuraVehicleState,
)
from hedp.adapters.sakura.operation import (
    SakuraCapability,
    SakuraCapabilitySnapshot,
    SakuraClimateRequest,
    SakuraDryRunOutcome,
    SakuraDryRunPlanner,
    SakuraLockRequest,
    SakuraOperation,
    SakuraSetCabinTemperatureRequest,
    SakuraStartChargingRequest,
    is_supported_operation_name,
)
from hedp.observations import ObservationTime, ObservedValue, Quality


NOW = datetime(2026, 7, 27, 7, tzinfo=timezone.utc)


def _good(value: object) -> ObservedValue:
    return ObservedValue(value, Quality.GOOD)


def _vehicle_state(**changes: object) -> SakuraVehicleState:
    values = {
        "target_ref": "family-car",
        "battery_percent": _good(72),
        "estimated_range_km": _good(128),
        "estimated_charge_completion_at": _good("2026-07-27T10:00:00+09:00"),
        "charging": _good(ChargingState.CHARGING),
        "plug": _good(PlugState.CONNECTED),
        "door_lock": _good(DoorLockState.LOCKED),
        "cabin_temperature_c": _good(25.5),
        "climate": _good(ClimateState.ON),
        "target_temperature_c": _good(24),
        "alert_codes": _good(("charge-port-open",)),
        "manufacturer_updated_at": _good("2026-07-27T06:59:00+09:00"),
        "time": ObservationTime(
            "2026-07-27T06:59:00+09:00",
            "2026-07-27T07:00:00+09:00",
        ),
        "quality": Quality.GOOD,
    }
    values.update(changes)
    return SakuraVehicleState(**values)  # type: ignore[arg-type]


def test_vehicle_state_has_typed_requested_fields_without_identifiers() -> None:
    state = _vehicle_state()

    assert state.battery_percent.value == 72
    assert state.door_lock.value is DoorLockState.LOCKED
    assert "family-car" not in repr(state)
    assert not hasattr(state, "vin")
    assert not hasattr(state, "location")


@pytest.mark.parametrize(
    "field,value",
    [
        ("charging", "charging"),
        ("plug", "connected"),
        ("door_lock", "locked"),
        ("climate", "on"),
    ],
)
def test_vehicle_state_rejects_untyped_enum_values(
    field: str,
    value: str,
) -> None:
    with pytest.raises(TypeError, match="value must be"):
        _vehicle_state(**{field: _good(value)})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_vehicle_state_and_temperature_request_reject_non_finite_numbers(
    value: float,
) -> None:
    with pytest.raises(ValueError, match="finite"):
        _vehicle_state(battery_percent=_good(value))
    with pytest.raises(ValueError, match="finite"):
        SakuraSetCabinTemperatureRequest(*_base(), value)


def _snapshot() -> SakuraCapabilitySnapshot:
    return SakuraCapabilitySnapshot(
        target_alias="family-car",
        supported_capabilities=frozenset(SakuraCapability),
        observed_at=NOW - timedelta(seconds=5),
        max_age=timedelta(minutes=2),
        cabin_temperature_range_c=(18, 30),
    )


def _base() -> tuple[str, str, datetime]:
    return "op-1", "family-car", NOW - timedelta(seconds=1)


@pytest.mark.parametrize(
    "operation_request",
    [
        SakuraStartChargingRequest(*_base()),
        SakuraClimateRequest(*_base(), True),
        SakuraClimateRequest(*_base(), False),
        SakuraSetCabinTemperatureRequest(*_base(), 24),
        SakuraLockRequest(*_base()),
    ],
)
def test_supported_sakura_requests_are_dry_run_only(
    operation_request: object,
) -> None:
    result = SakuraDryRunPlanner(_snapshot()).evaluate(
        operation_request,  # type: ignore[arg-type]
        evaluated_at=NOW,
    )

    assert result.outcome is SakuraDryRunOutcome.WOULD_DISPATCH
    assert result.dispatch_attempted is False


def test_temperature_uses_observed_range_not_a_guessed_global_range() -> None:
    result = SakuraDryRunPlanner(_snapshot()).evaluate(
        SakuraSetCabinTemperatureRequest(*_base(), 31),
        evaluated_at=NOW,
    )

    assert result.outcome is SakuraDryRunOutcome.WOULD_BLOCK
    assert result.reason_code == "parameter_not_advertised"


def test_unlock_is_explicitly_unsupported_with_no_bypass_type() -> None:
    assert is_supported_operation_name("unlock") is False
    assert "unlock" not in {item.value for item in SakuraOperation}
    with pytest.raises(ValueError):
        SakuraOperation("unlock")
    assert not hasattr(SakuraDryRunPlanner(_snapshot()), "dispatch")


def test_operation_names_are_distinct_from_capability_names() -> None:
    assert is_supported_operation_name("start_charging") is True
    assert is_supported_operation_name("start_climate") is True
    assert is_supported_operation_name("stop_climate") is True
    assert is_supported_operation_name("set_cabin_temperature") is True
    assert is_supported_operation_name("charge") is False
    assert is_supported_operation_name("climate") is False
    assert SakuraStartChargingRequest(*_base()).capability is SakuraCapability.CHARGE
    assert (
        SakuraClimateRequest(*_base(), False).operation is SakuraOperation.STOP_CLIMATE
    )
