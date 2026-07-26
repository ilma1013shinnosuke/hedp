from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from hedp.adapters.ecocute import (
    EchonetFrame,
    EchonetProperty,
    ObservationSource,
    build_get_request,
    build_setc_request,
    confirmed_property_name,
    normalize_requested_observation,
)
from hedp.adapters.ecocute.echonet import decode_known_property
from hedp.adapters.ecocute.operation import (
    EcoCuteOperation,
    EcoCuteOperationAdapter,
    EcoCuteOperationCommand,
    OperationQualification,
    RuntimeCapabilitySnapshot,
    VerificationStatus,
    classify_operation,
)
from hedp.adapters.ecocute.transport import EcoCuteSetUdpTransport
from hedp.observations import ObservationTime, Quality


NOW = datetime(2026, 7, 26, 1, 2, 3, tzinfo=timezone.utc)
TIME = ObservationTime(NOW.isoformat(), NOW.isoformat())


class FakeSetPropertiesTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def set_properties(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return object()


class FakeReadTransport:
    def __init__(self, epc: int, data: bytes) -> None:
        self.epc = epc
        self.data = data
        self.calls: list[dict[str, object]] = []

    def get(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(
            frame=EchonetFrame(
                2,
                bytes((0x02, 0x6B, 0x01)),
                bytes((0x05, 0xFF, 0x01)),
                0x72,
                (EchonetProperty(self.epc, self.data),),
            )
        )


def adapter(
    setter: FakeSetPropertiesTransport,
    reader: FakeReadTransport,
) -> EcoCuteOperationAdapter:
    ids = iter((1, 2))
    return EcoCuteOperationAdapter(
        setter,  # type: ignore[arg-type]
        reader,
        capability_snapshot=RuntimeCapabilitySnapshot(
            "main_water_heater",
            frozenset((0x93, 0xB0, 0xC0, 0xE3)),
            frozenset((0xB0, 0xB2, 0xC0, 0xE3)),
            NOW,
            timedelta(minutes=5),
        ),
        readback_delay_seconds=0,
        transaction_id_factory=lambda: next(ids),
        now=lambda: NOW,
    )


def test_get_builder_enforces_four_property_aif_batch() -> None:
    with pytest.raises(ValueError, match="at most four"):
        build_get_request(
            transaction_id=1,
            epcs=(0x80, 0x88, 0xB0, 0xB2, 0xC0),
        )


@pytest.mark.parametrize(
    ("epc", "name", "data", "value"),
    [
        (0xC0, "daytime_boost_allowed", b"\x41", True),
        (0xE3, "bath_auto_enabled", b"\x42", False),
        (0xC7, "energy_shift_participation", b"\x01", "participating"),
        (0xC8, "heating_start_base_time", b"\x04", "00:00"),
        (0xC9, "energy_shift_count", b"\x02", 2),
        (0xCA, "daytime_heating_shift_time_1", b"\x08", "17:00"),
        (0xCB, "predicted_heating_energy_1", bytes(16), None),
        (0xCC, "hourly_energy_profile_1", bytes(8), None),
    ],
)
def test_confirmed_energy_shift_names_and_decoders(
    epc: int,
    name: str,
    data: bytes,
    value: object,
) -> None:
    assert confirmed_property_name(epc) == name
    assert decode_known_property(EchonetProperty(epc, data)) == value


def test_partial_get_marks_requested_omission_missing_and_ignores_extra() -> None:
    frame = EchonetFrame(
        1,
        bytes((0x02, 0x6B, 0x01)),
        bytes((0x05, 0xFF, 0x01)),
        0x72,
        (
            EchonetProperty(0x80, b"\x30"),
            EchonetProperty(0xE1, b"\x01\x2c"),
        ),
    )
    observation = normalize_requested_observation(
        frame,
        requested_epcs=(0x80, 0xB0),
        time=TIME,
    )

    assert observation.source is ObservationSource.PERIODIC
    assert [item.epc for item in observation.properties] == [0x80, 0xB0]
    assert observation.properties[1].reading.quality is Quality.MISSING
    assert observation.properties[1].reading.reason == "requested_property_missing"


def test_two_property_setc_preserves_remote_marker_order() -> None:
    raw = build_setc_request(
        transaction_id=7,
        properties=(
            EchonetProperty(0x93, b"\x41"),
            EchonetProperty(0xB0, b"\x42"),
        ),
    )

    assert raw.hex() == "1081000705ff01026b016102930141b00142"


def test_verified_boost_dry_run_is_capability_gated_and_sends_nothing() -> None:
    setter = FakeSetPropertiesTransport()
    result = adapter(setter, FakeReadTransport(0xB0, b"\x42")).execute_operation(
        EcoCuteOperationCommand(
            "main_water_heater",
            EcoCuteOperation.BOOST_START,
        )
    )

    assert result.operation is None
    assert result.dry_run.qualification is OperationQualification.VERIFIED
    assert result.dry_run.required_set_epcs == (0x93, 0xB0)
    assert result.dry_run.verification_epc == 0xB2
    assert not result.dry_run.would_dispatch
    assert setter.calls == []


def test_dry_run_false_is_blocked_before_any_write_transport() -> None:
    setter = FakeSetPropertiesTransport()
    reader = FakeReadTransport(0xB2, b"\x41")

    with pytest.raises(PermissionError, match="live dispatch is disabled"):
        adapter(setter, reader).execute_operation(
            EcoCuteOperationCommand(
                "main_water_heater",
                EcoCuteOperation.BOOST_START,
                dry_run=False,
            )
        )

    assert setter.calls == []
    assert reader.calls == []
    assert not hasattr(EcoCuteSetUdpTransport, "set_properties")


@pytest.mark.parametrize(
    ("operation", "observed"),
    [
        (EcoCuteOperation.BOOST_START, b"\x41"),
        (EcoCuteOperation.BOOST_STOP, b"\x42"),
    ],
)
def test_boost_state_verification_uses_actual_heating_state(
    operation: EcoCuteOperation,
    observed: bytes,
) -> None:
    setter = FakeSetPropertiesTransport()
    reader = FakeReadTransport(0xB2, observed)

    verification = adapter(setter, reader).verify_operation_state(
        EcoCuteOperationCommand("main_water_heater", operation)
    )

    assert verification.epc == 0xB2
    assert verification.status is VerificationStatus.MATCHED
    assert setter.calls == []
    assert reader.calls[0]["epcs"] == (0xB2,)


def test_bath_and_daytime_operations_remain_dry_run_only() -> None:
    setter = FakeSetPropertiesTransport()
    typed_adapter = adapter(setter, FakeReadTransport(0xE3, b"\x41"))

    dry_run = typed_adapter.execute_operation(
        EcoCuteOperationCommand(
            "main_water_heater",
            EcoCuteOperation.BATH_AUTO_ON,
        )
    )
    assert dry_run.dry_run.qualification is OperationQualification.OFFLINE_QUALIFIED
    assert not dry_run.dry_run.would_dispatch

    with pytest.raises(PermissionError, match="live dispatch is disabled"):
        typed_adapter.execute_operation(
            EcoCuteOperationCommand(
                "main_water_heater",
                EcoCuteOperation.DAYTIME_BOOST_ALLOW,
                dry_run=False,
            )
        )
    assert setter.calls == []


def test_two_property_operation_requires_both_runtime_set_epcs() -> None:
    setter = FakeSetPropertiesTransport()
    typed_adapter = EcoCuteOperationAdapter(
        setter,  # type: ignore[arg-type]
        FakeReadTransport(0xB0, b"\x42"),
        capability_snapshot=RuntimeCapabilitySnapshot(
            "main_water_heater",
            frozenset((0xB0,)),
            frozenset((0xB0,)),
            NOW,
            timedelta(minutes=5),
        ),
        now=lambda: NOW,
    )

    with pytest.raises(PermissionError, match="runtime Set map"):
        typed_adapter.execute_operation(
            EcoCuteOperationCommand(
                "main_water_heater",
                EcoCuteOperation.BOOST_START,
            )
        )
    assert setter.calls == []


def test_unknown_typed_operation_is_explicitly_unsupported() -> None:
    support = classify_operation("manufacturer_magic")

    assert support.operation is None
    assert support.qualification is OperationQualification.UNSUPPORTED
    assert support.reason == "operation_not_supported"
