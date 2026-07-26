"""Typed, offline-only BRAVIA operation planning contracts.

No REST/IRCC endpoint, authentication scheme, IRCC code, Wake-on-LAN packet,
or write transport belongs here.  A successful result means only that a
capability-backed request *would* be eligible for dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import re
from typing import TypeAlias


_SAFE_REF = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class BraviaCapability(str, Enum):
    POWER = "power"
    VOLUME = "volume"
    MUTE = "mute"
    INPUT = "input"
    CHANNEL = "channel"
    APP = "app"
    WAKE_ON_LAN = "wake_on_lan"


# Operation and capability intentionally use the same discovered vocabulary.
BraviaOperation = BraviaCapability


class BraviaPowerSetting(str, Enum):
    ON = "on"
    OFF = "off"


class BraviaDryRunOutcome(str, Enum):
    WOULD_DISPATCH = "would_dispatch"
    WOULD_BLOCK = "would_block"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class BraviaCapabilitySnapshot:
    """Short-lived abilities observed from the exact target."""

    target_alias: str
    supported_capabilities: frozenset[BraviaCapability]
    observed_at: datetime
    max_age: timedelta
    volume_range: tuple[int, int] | None = None
    input_aliases: frozenset[str] = frozenset()
    channel_aliases: frozenset[str] = field(default=frozenset(), repr=False)
    app_aliases: frozenset[str] = field(default=frozenset(), repr=False)

    def __post_init__(self) -> None:
        _require_safe_ref("target_alias", self.target_alias)
        if not isinstance(self.supported_capabilities, frozenset):
            raise TypeError("supported_capabilities must be a frozenset")
        if any(
            not isinstance(item, BraviaCapability)
            for item in self.supported_capabilities
        ):
            raise TypeError(
                "supported_capabilities must contain BraviaCapability values"
            )
        _require_aware("observed_at", self.observed_at)
        _require_duration("max_age", self.max_age)
        if self.volume_range is not None:
            if not isinstance(self.volume_range, tuple) or len(self.volume_range) != 2:
                raise TypeError("volume_range must be a two-item tuple or None")
            minimum, maximum = self.volume_range
            _require_int("volume_range minimum", minimum)
            _require_int("volume_range maximum", maximum)
            if minimum > maximum:
                raise ValueError("volume_range minimum must not exceed maximum")
        for name in ("input_aliases", "channel_aliases", "app_aliases"):
            values = getattr(self, name)
            if not isinstance(values, frozenset):
                raise TypeError(f"{name} must be a frozenset")
            for value in values:
                _require_safe_ref(name, value)

    def is_fresh_at(self, value: datetime) -> bool:
        _require_aware("evaluated_at", value)
        age = value.astimezone(timezone.utc) - self.observed_at.astimezone(timezone.utc)
        return timedelta(0) <= age <= self.max_age


@dataclass(frozen=True)
class _Request:
    operation_id: str
    target_alias: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_safe_ref("operation_id", self.operation_id)
        _require_safe_ref("target_alias", self.target_alias)
        _require_aware("requested_at", self.requested_at)


@dataclass(frozen=True)
class BraviaPowerRequest(_Request):
    desired: BraviaPowerSetting
    capability: BraviaCapability = BraviaCapability.POWER

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.desired, BraviaPowerSetting):
            raise TypeError("desired must be a BraviaPowerSetting")
        _require_fixed_capability(self.capability, BraviaCapability.POWER)


@dataclass(frozen=True)
class BraviaVolumeRequest(_Request):
    level: int
    capability: BraviaCapability = BraviaCapability.VOLUME

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_int("level", self.level)
        _require_fixed_capability(self.capability, BraviaCapability.VOLUME)


@dataclass(frozen=True)
class BraviaMuteRequest(_Request):
    muted: bool
    capability: BraviaCapability = BraviaCapability.MUTE

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.muted, bool):
            raise TypeError("muted must be a boolean")
        _require_fixed_capability(self.capability, BraviaCapability.MUTE)


@dataclass(frozen=True)
class BraviaInputRequest(_Request):
    input_alias: str
    capability: BraviaCapability = BraviaCapability.INPUT

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_safe_ref("input_alias", self.input_alias)
        _require_fixed_capability(self.capability, BraviaCapability.INPUT)


@dataclass(frozen=True)
class BraviaChannelRequest(_Request):
    channel_alias: str = field(repr=False)
    capability: BraviaCapability = BraviaCapability.CHANNEL

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_safe_ref("channel_alias", self.channel_alias)
        _require_fixed_capability(self.capability, BraviaCapability.CHANNEL)


@dataclass(frozen=True)
class BraviaAppRequest(_Request):
    app_alias: str = field(repr=False)
    capability: BraviaCapability = BraviaCapability.APP

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_safe_ref("app_alias", self.app_alias)
        _require_fixed_capability(self.capability, BraviaCapability.APP)


@dataclass(frozen=True)
class BraviaWakeOnLanRequest(_Request):
    capability: BraviaCapability = BraviaCapability.WAKE_ON_LAN

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_fixed_capability(self.capability, BraviaCapability.WAKE_ON_LAN)


BraviaOperationRequest: TypeAlias = (
    BraviaPowerRequest
    | BraviaVolumeRequest
    | BraviaMuteRequest
    | BraviaInputRequest
    | BraviaChannelRequest
    | BraviaAppRequest
    | BraviaWakeOnLanRequest
)


@dataclass(frozen=True)
class BraviaDryRunResult:
    request: BraviaOperationRequest
    outcome: BraviaDryRunOutcome
    reason_code: str
    dispatch_attempted: bool = False

    def __post_init__(self) -> None:
        if self.dispatch_attempted:
            raise ValueError("BRAVIA dry-run cannot dispatch")


class BraviaDryRunPlanner:
    """Evaluate typed operations without owning any device transport."""

    def __init__(self, snapshot: BraviaCapabilitySnapshot) -> None:
        self._snapshot = snapshot

    def evaluate(
        self,
        request: BraviaOperationRequest,
        *,
        evaluated_at: datetime,
    ) -> BraviaDryRunResult:
        _require_aware("evaluated_at", evaluated_at)
        if not isinstance(
            request,
            (
                BraviaPowerRequest,
                BraviaVolumeRequest,
                BraviaMuteRequest,
                BraviaInputRequest,
                BraviaChannelRequest,
                BraviaAppRequest,
                BraviaWakeOnLanRequest,
            ),
        ):
            raise TypeError("request must be a typed BRAVIA operation request")
        if request.target_alias != self._snapshot.target_alias:
            return self._result(
                request, BraviaDryRunOutcome.WOULD_BLOCK, "target_mismatch"
            )
        if request.requested_at > evaluated_at:
            return self._result(
                request,
                BraviaDryRunOutcome.WOULD_BLOCK,
                "request_time_invalid",
            )
        if not self._snapshot.is_fresh_at(evaluated_at):
            return self._result(
                request,
                BraviaDryRunOutcome.INDETERMINATE,
                "capability_snapshot_stale",
            )
        if request.capability not in self._snapshot.supported_capabilities:
            return self._result(
                request,
                BraviaDryRunOutcome.WOULD_BLOCK,
                "capability_not_advertised",
            )
        parameter_reason = self._parameter_reason(request)
        if parameter_reason is not None:
            outcome = (
                BraviaDryRunOutcome.INDETERMINATE
                if parameter_reason == "parameter_capability_missing"
                else BraviaDryRunOutcome.WOULD_BLOCK
            )
            return self._result(request, outcome, parameter_reason)
        return self._result(
            request,
            BraviaDryRunOutcome.WOULD_DISPATCH,
            "conditions_satisfied",
        )

    def _parameter_reason(self, request: BraviaOperationRequest) -> str | None:
        if isinstance(request, BraviaVolumeRequest):
            if self._snapshot.volume_range is None:
                return "parameter_capability_missing"
            minimum, maximum = self._snapshot.volume_range
            if not minimum <= request.level <= maximum:
                return "parameter_not_advertised"
        aliases: frozenset[str] | None = None
        requested_alias: str | None = None
        if isinstance(request, BraviaInputRequest):
            aliases, requested_alias = self._snapshot.input_aliases, request.input_alias
        elif isinstance(request, BraviaChannelRequest):
            aliases, requested_alias = (
                self._snapshot.channel_aliases,
                request.channel_alias,
            )
        elif isinstance(request, BraviaAppRequest):
            aliases, requested_alias = self._snapshot.app_aliases, request.app_alias
        if aliases is not None:
            if not aliases:
                return "parameter_capability_missing"
            if requested_alias not in aliases:
                return "parameter_not_advertised"
        return None

    @staticmethod
    def _result(
        request: BraviaOperationRequest,
        outcome: BraviaDryRunOutcome,
        reason_code: str,
    ) -> BraviaDryRunResult:
        return BraviaDryRunResult(request, outcome, reason_code)


BraviaDryRunOperationAdapter = BraviaDryRunPlanner


def _require_fixed_capability(
    actual: BraviaCapability, expected: BraviaCapability
) -> None:
    if actual is not expected:
        raise ValueError(f"capability must be {expected.value}")


def _require_safe_ref(name: str, value: str) -> None:
    if not isinstance(value, str) or not _SAFE_REF.fullmatch(value):
        raise ValueError(f"{name} must be a safe opaque reference")


def _require_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")


def _require_aware(name: str, value: datetime) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _require_duration(name: str, value: timedelta) -> None:
    if not isinstance(value, timedelta):
        raise TypeError(f"{name} must be a timedelta")
    if value <= timedelta(0) or value > timedelta(hours=24):
        raise ValueError(f"{name} must be greater than 0 and at most 24 hours")
