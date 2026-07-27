"""Typed SwitchBot lighting-mode contracts without private protocol bytes.

SwitchBot uses the word ``scene`` for two different concepts:

* an account-level automation scene exposed by OpenAPI; and
* a device-local lighting effect selected by the app or a BLE implementation.

They must not share one command type.  This module records the distinction,
normalizes observable runtime modes, and creates side-effect-free plans for an
optional BLE backend.  It deliberately does not contain vendor identifiers,
encrypted BLE commands, microphone handling, or a live transport.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from hedp.observations import ObservedValue, Quality


_SAFE_ALIAS = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class LightRuntimeMode(str, Enum):
    """General mode observable from a compatible light advertisement."""

    RGB = "rgb"
    DEVICE_EFFECT = "device_effect"
    MUSIC = "music"
    CONTROLLER = "controller"
    COLOR_TEMPERATURE = "color_temperature"


class LightSceneDomain(str, Enum):
    """Two unrelated vendor concepts that are both called a scene."""

    AUTOMATION_SCENE = "automation_scene"
    DEVICE_EFFECT = "device_effect"


class LightModeTransport(str, Enum):
    """Transport boundary for one mode capability."""

    PUBLIC_OPENAPI_DEVICE = "public_openapi_device"
    PUBLIC_OPENAPI_AUTOMATION = "public_openapi_automation"
    OPTIONAL_BLE_BACKEND = "optional_ble_backend"
    APP_OR_DEVICE_CONTROLLER = "app_or_device_controller"


class CapabilityEvidence(str, Enum):
    """Strength and origin of a capability claim."""

    OFFICIAL_PUBLIC_API = "official_public_api"
    OFFICIAL_PRODUCT_DOCUMENTATION = "official_product_documentation"
    OFFICIAL_BLE_STATUS = "official_ble_status"
    THIRD_PARTY_BLE_LIBRARY = "third_party_ble_library"
    LOCAL_CONFIRMED_INTENT = "local_confirmed_intent"
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class RuntimeModeObservation:
    """A general mode observation; it never invents an exact effect name."""

    mode: ObservedValue[LightRuntimeMode]
    raw_mode: int | None
    evidence: CapabilityEvidence

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, CapabilityEvidence):
            raise TypeError("evidence must be CapabilityEvidence")
        if self.raw_mode is not None and (
            isinstance(self.raw_mode, bool) or not isinstance(self.raw_mode, int)
        ):
            raise TypeError("raw_mode must be an integer or None")

    def safe_summary(self) -> dict[str, object]:
        return {
            "mode": self.mode.value.value if self.mode.value is not None else None,
            "quality": self.mode.quality.value,
            "reason": self.mode.reason,
            "evidence": self.evidence.value,
            "exact_effect_observed": False,
        }


_BLE_RUNTIME_MODES = {
    2: LightRuntimeMode.RGB,
    3: LightRuntimeMode.DEVICE_EFFECT,
    4: LightRuntimeMode.MUSIC,
    5: LightRuntimeMode.CONTROLLER,
    6: LightRuntimeMode.COLOR_TEMPERATURE,
}


def normalize_ble_runtime_mode(raw_mode: object) -> RuntimeModeObservation:
    """Normalize the documented mode nibble without guessing unknown values."""

    if isinstance(raw_mode, bool) or not isinstance(raw_mode, int):
        return RuntimeModeObservation(
            mode=ObservedValue(None, Quality.INVALID, "runtime_mode_not_integer"),
            raw_mode=None,
            evidence=CapabilityEvidence.OFFICIAL_BLE_STATUS,
        )
    mode = _BLE_RUNTIME_MODES.get(raw_mode)
    if mode is None:
        return RuntimeModeObservation(
            mode=ObservedValue(None, Quality.UNKNOWN, "runtime_mode_unknown"),
            raw_mode=raw_mode,
            evidence=CapabilityEvidence.OFFICIAL_BLE_STATUS,
        )
    return RuntimeModeObservation(
        mode=ObservedValue(mode, Quality.GOOD),
        raw_mode=raw_mode,
        evidence=CapabilityEvidence.OFFICIAL_BLE_STATUS,
    )


@dataclass(frozen=True)
class DeviceEffectCatalog:
    """Effect aliases supplied by a versioned optional BLE implementation."""

    aliases: frozenset[str]
    evidence: CapabilityEvidence

    def __post_init__(self) -> None:
        if not isinstance(self.aliases, frozenset) or not self.aliases:
            raise ValueError("aliases must be a non-empty frozenset")
        if any(not _SAFE_ALIAS.fullmatch(alias) for alias in self.aliases):
            raise ValueError("effect aliases must be safe local aliases")
        if self.evidence not in {
            CapabilityEvidence.THIRD_PARTY_BLE_LIBRARY,
            CapabilityEvidence.LOCAL_CONFIRMED_INTENT,
        }:
            raise ValueError("effect catalog needs BLE or local evidence")


@dataclass(frozen=True)
class LightModePlan:
    """Side-effect-free plan consumed later by ExecutionGate and a live port."""

    target_alias: str
    requested_mode: LightRuntimeMode
    effect_alias: str | None
    transport: LightModeTransport
    evidence: CapabilityEvidence
    dry_run: bool
    dispatch_allowed: bool
    general_mode_readback_supported: bool
    exact_selection_readback_supported: bool
    reason: str

    def __post_init__(self) -> None:
        if not _SAFE_ALIAS.fullmatch(self.target_alias):
            raise ValueError("target_alias must be a safe local alias")
        if self.effect_alias is not None and not _SAFE_ALIAS.fullmatch(
            self.effect_alias
        ):
            raise ValueError("effect_alias must be a safe local alias")
        if not self.dry_run:
            raise ValueError("light mode plans in this module must remain dry-run")

    def safe_summary(self) -> dict[str, object]:
        return {
            "target_alias": self.target_alias,
            "requested_mode": self.requested_mode.value,
            "effect_alias": self.effect_alias,
            "transport": self.transport.value,
            "evidence": self.evidence.value,
            "dry_run": self.dry_run,
            "dispatch_allowed": self.dispatch_allowed,
            "general_mode_readback_supported": (
                self.general_mode_readback_supported
            ),
            "exact_selection_readback_supported": (
                self.exact_selection_readback_supported
            ),
            "reason": self.reason,
        }


class MusicAudioSource(str, Enum):
    """Confirmed audio source for reactive lighting."""

    DEVICE_BUILT_IN_MICROPHONE = "device_built_in_microphone"


@dataclass(frozen=True)
class MusicModeCapability:
    """What is known without inventing a HESTIA control path."""

    supported_by_product: bool = True
    audio_source: MusicAudioSource = MusicAudioSource.DEVICE_BUILT_IN_MICROPHONE
    app_control: bool = True
    device_controller_button: bool = True
    sensitivity_adjustment: bool = True
    public_cloud_control: bool = False
    public_cloud_readback: bool = False
    ble_control_verified: bool = False
    ble_mode_readback_candidate: bool = True
    sensitivity_readback_verified: bool = False
    palette_readback_verified: bool = False
    evidence: CapabilityEvidence = (
        CapabilityEvidence.OFFICIAL_PRODUCT_DOCUMENTATION
    )

    def safe_summary(self) -> dict[str, object]:
        return {
            "supported_by_product": self.supported_by_product,
            "audio_source": self.audio_source.value,
            "app_control": self.app_control,
            "device_controller_button": self.device_controller_button,
            "sensitivity_adjustment": self.sensitivity_adjustment,
            "public_cloud_control": self.public_cloud_control,
            "public_cloud_readback": self.public_cloud_readback,
            "ble_control_verified": self.ble_control_verified,
            "ble_mode_readback_candidate": self.ble_mode_readback_candidate,
            "sensitivity_readback_verified": (
                self.sensitivity_readback_verified
            ),
            "palette_readback_verified": self.palette_readback_verified,
            "evidence": self.evidence.value,
        }


def plan_device_effect(
    *,
    target_alias: str,
    effect_alias: str,
    transport: LightModeTransport,
    catalog: DeviceEffectCatalog | None,
) -> LightModePlan:
    """Plan one built-in effect without confusing it with an automation scene."""

    if transport is not LightModeTransport.OPTIONAL_BLE_BACKEND:
        return LightModePlan(
            target_alias=target_alias,
            requested_mode=LightRuntimeMode.DEVICE_EFFECT,
            effect_alias=effect_alias,
            transport=transport,
            evidence=CapabilityEvidence.OFFICIAL_PUBLIC_API,
            dry_run=True,
            dispatch_allowed=False,
            general_mode_readback_supported=False,
            exact_selection_readback_supported=False,
            reason="device_effect_not_in_public_device_api",
        )
    if catalog is None or effect_alias not in catalog.aliases:
        return LightModePlan(
            target_alias=target_alias,
            requested_mode=LightRuntimeMode.DEVICE_EFFECT,
            effect_alias=effect_alias,
            transport=transport,
            evidence=(
                catalog.evidence
                if catalog is not None
                else CapabilityEvidence.UNVERIFIED
            ),
            dry_run=True,
            dispatch_allowed=False,
            general_mode_readback_supported=True,
            exact_selection_readback_supported=False,
            reason="effect_alias_not_verified",
        )
    return LightModePlan(
        target_alias=target_alias,
        requested_mode=LightRuntimeMode.DEVICE_EFFECT,
        effect_alias=effect_alias,
        transport=transport,
        evidence=catalog.evidence,
        dry_run=True,
        dispatch_allowed=True,
        general_mode_readback_supported=True,
        exact_selection_readback_supported=False,
        reason="optional_ble_backend_required",
    )


def plan_music_mode(
    *,
    target_alias: str,
    transport: LightModeTransport,
) -> LightModePlan:
    """Represent Music as pending until its sound source and command are proven."""

    locally_supported = (
        transport is LightModeTransport.APP_OR_DEVICE_CONTROLLER
    )
    return LightModePlan(
        target_alias=target_alias,
        requested_mode=LightRuntimeMode.MUSIC,
        effect_alias=None,
        transport=transport,
        evidence=(
            CapabilityEvidence.OFFICIAL_PRODUCT_DOCUMENTATION
            if locally_supported
            else CapabilityEvidence.OFFICIAL_PUBLIC_API
        ),
        dry_run=True,
        dispatch_allowed=False,
        general_mode_readback_supported=(
            transport is LightModeTransport.OPTIONAL_BLE_BACKEND
        ),
        exact_selection_readback_supported=False,
        reason=(
            "music_sound_source_and_activation_unverified"
            if locally_supported
            else "music_not_in_public_device_api"
        ),
    )


def scene_domains() -> tuple[dict[str, object], ...]:
    """Return the stable public boundary without account or device identifiers."""

    return (
        {
            "domain": LightSceneDomain.AUTOMATION_SCENE.value,
            "transport": LightModeTransport.PUBLIC_OPENAPI_AUTOMATION.value,
            "lists_and_executes_account_automation": True,
            "selects_device_effect": False,
        },
        {
            "domain": LightSceneDomain.DEVICE_EFFECT.value,
            "transport": LightModeTransport.OPTIONAL_BLE_BACKEND.value,
            "lists_and_executes_account_automation": False,
            "selects_device_effect": True,
        },
    )
