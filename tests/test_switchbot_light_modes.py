from __future__ import annotations

import json
from pathlib import Path

import pytest

from hedp.observations import Quality
from hedp.adapters.switchbot.light_modes import (
    CapabilityEvidence,
    DeviceEffectCatalog,
    LightModeTransport,
    LightRuntimeMode,
    MusicModeCapability,
    normalize_ble_runtime_mode,
    plan_device_effect,
    plan_music_mode,
    scene_domains,
)

_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "switchbot"
    / "strip_light_3_modes_anonymous.json"
)


def test_anonymous_mode_fixture_matches_typed_contract() -> None:
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))

    for case in fixture["runtime_mode_cases"]:
        observed = normalize_ble_runtime_mode(case["raw_mode"])
        assert observed.mode.value is not None
        assert observed.mode.value.value == case["expected"]

    unknown = normalize_ble_runtime_mode(fixture["unknown_runtime_mode"])
    assert unknown.mode.quality is Quality.UNKNOWN
    assert unknown.mode.value is None

    music = MusicModeCapability().safe_summary()
    assert music["audio_source"] == fixture["music_capability"]["audio_source"]
    assert (
        music["public_cloud_control"]
        is fixture["music_capability"]["public_cloud_control"]
    )
    assert (
        music["ble_control_verified"]
        is fixture["music_capability"]["ble_control_verified"]
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (2, LightRuntimeMode.RGB),
        (3, LightRuntimeMode.DEVICE_EFFECT),
        (4, LightRuntimeMode.MUSIC),
        (5, LightRuntimeMode.CONTROLLER),
        (6, LightRuntimeMode.COLOR_TEMPERATURE),
    ],
)
def test_known_ble_runtime_modes_are_typed(
    raw: int,
    expected: LightRuntimeMode,
) -> None:
    observed = normalize_ble_runtime_mode(raw)

    assert observed.mode.quality is Quality.GOOD
    assert observed.mode.value is expected
    assert observed.safe_summary()["exact_effect_observed"] is False


def test_unknown_and_invalid_runtime_modes_are_not_guessed() -> None:
    unknown = normalize_ble_runtime_mode(15)
    invalid = normalize_ble_runtime_mode("music")

    assert unknown.mode.quality is Quality.UNKNOWN
    assert unknown.mode.value is None
    assert invalid.mode.quality is Quality.INVALID
    assert invalid.mode.value is None


def test_account_automation_scene_and_device_effect_are_separate() -> None:
    domains = scene_domains()

    assert domains[0]["domain"] == "automation_scene"
    assert domains[0]["selects_device_effect"] is False
    assert domains[1]["domain"] == "device_effect"
    assert domains[1]["lists_and_executes_account_automation"] is False


def test_public_device_api_cannot_plan_a_built_in_effect() -> None:
    plan = plan_device_effect(
        target_alias="strip-light-3",
        effect_alias="christmas",
        transport=LightModeTransport.PUBLIC_OPENAPI_DEVICE,
        catalog=None,
    )

    assert plan.dry_run is True
    assert plan.dispatch_allowed is False
    assert plan.reason == "device_effect_not_in_public_device_api"
    assert plan.general_mode_readback_supported is False


def test_optional_ble_catalog_allows_only_verified_effect_aliases() -> None:
    catalog = DeviceEffectCatalog(
        aliases=frozenset({"christmas", "ocean"}),
        evidence=CapabilityEvidence.THIRD_PARTY_BLE_LIBRARY,
    )

    accepted = plan_device_effect(
        target_alias="strip-light-3",
        effect_alias="ocean",
        transport=LightModeTransport.OPTIONAL_BLE_BACKEND,
        catalog=catalog,
    )
    rejected = plan_device_effect(
        target_alias="strip-light-3",
        effect_alias="private-preset",
        transport=LightModeTransport.OPTIONAL_BLE_BACKEND,
        catalog=catalog,
    )

    assert accepted.dispatch_allowed is True
    assert accepted.general_mode_readback_supported is True
    assert accepted.exact_selection_readback_supported is False
    assert rejected.dispatch_allowed is False
    assert rejected.reason == "effect_alias_not_verified"


def test_music_is_not_exposed_as_a_public_device_command() -> None:
    plan = plan_music_mode(
        target_alias="strip-light-3",
        transport=LightModeTransport.PUBLIC_OPENAPI_DEVICE,
    )

    assert plan.requested_mode is LightRuntimeMode.MUSIC
    assert plan.dispatch_allowed is False
    assert plan.reason == "music_not_in_public_device_api"


def test_music_capability_records_device_microphone_without_live_control() -> None:
    capability = MusicModeCapability().safe_summary()

    assert capability["supported_by_product"] is True
    assert capability["audio_source"] == "device_built_in_microphone"
    assert capability["app_control"] is True
    assert capability["device_controller_button"] is True
    assert capability["sensitivity_adjustment"] is True
    assert capability["public_cloud_control"] is False
    assert capability["public_cloud_readback"] is False
    assert capability["ble_control_verified"] is False


def test_app_or_controller_music_plan_remains_non_dispatchable() -> None:
    plan = plan_music_mode(
        target_alias="strip-light-3",
        transport=LightModeTransport.APP_OR_DEVICE_CONTROLLER,
    )

    assert plan.dispatch_allowed is False
    assert plan.reason == "music_sound_source_and_activation_unverified"


def test_mode_plan_rejects_household_identifiers_as_aliases() -> None:
    with pytest.raises(ValueError, match="target_alias"):
        plan_music_mode(
            target_alias="private id with spaces",
            transport=LightModeTransport.APP_OR_DEVICE_CONTROLLER,
        )
