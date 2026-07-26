"""Typed, offline-only operation plans for Smart LEDZ 2.0.4."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import re
from typing import Callable

from hedp.observations import Quality


_SAFE_ALIAS = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,79}$")


class SmartLedzOperation(str, Enum):
    SCENE_RUN = "scene_run"
    SCHEDULE_SELECT = "schedule_select"


class DryRunSupport(str, Enum):
    VERIFIED = "verified"
    INDETERMINATE = "indeterminate"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class SmartLedzDryRun:
    """A sanitized plan; creating it never opens a transport."""

    operation: SmartLedzOperation
    target_alias: str
    support: DryRunSupport
    reason: str
    command: Mapping[str, object] | None = field(default=None, repr=False)

    @property
    def would_dispatch(self) -> bool:
        return self.support is DryRunSupport.VERIFIED


@dataclass(frozen=True)
class SmartLedzCapabilitySnapshot:
    """Fresh readback evidence for one exact gateway and its scene relations."""

    gateway_id: int = field(repr=False)
    group_scenes: Mapping[str, frozenset[str]] = field(repr=False)
    observed_at: datetime
    max_age: timedelta
    quality: Quality
    scene_run_supported: bool
    scene_readback_supported: bool

    def __post_init__(self) -> None:
        _identifier("gateway_id", self.gateway_id)
        _aware("observed_at", self.observed_at)
        if (
            not isinstance(self.max_age, timedelta)
            or self.max_age <= timedelta(0)
            or self.max_age > timedelta(hours=24)
        ):
            raise ValueError("max_age must be greater than 0 and at most 24 hours")
        if not isinstance(self.quality, Quality):
            raise TypeError("quality must be a Quality value")
        if not isinstance(self.scene_run_supported, bool):
            raise TypeError("scene_run_supported must be a boolean")
        if not isinstance(self.scene_readback_supported, bool):
            raise TypeError("scene_readback_supported must be a boolean")
        for group_alias, scene_aliases in self.group_scenes.items():
            _alias(group_alias)
            if not isinstance(scene_aliases, frozenset):
                raise TypeError("group scene aliases must be frozensets")
            for scene_alias in scene_aliases:
                _alias(scene_alias)
        object.__setattr__(
            self,
            "group_scenes",
            {
                group_alias: frozenset(scene_aliases)
                for group_alias, scene_aliases in self.group_scenes.items()
            },
        )

    def is_fresh_at(self, value: datetime) -> bool:
        _aware("evaluated_at", value)
        age = value.astimezone(timezone.utc) - self.observed_at.astimezone(timezone.utc)
        return timedelta(0) <= age <= self.max_age


class SmartLedzDryRunPlanner:
    """Resolve safe aliases into verified wire shapes without dispatching.

    Scene execution has an observed command shape.  Weekly schedule selection
    remains explicitly unsupported because the recovered ``autoDaily`` shape
    has no anonymous response/read-back fixture establishing selection
    semantics.
    """

    def __init__(
        self,
        *,
        gateway_id: int,
        group_aliases: Mapping[str, int],
        scene_aliases: Mapping[str, int],
        schedule_aliases: Mapping[str, int],
        capability_snapshot: SmartLedzCapabilitySnapshot | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._gateway_id = _identifier("gateway_id", gateway_id)
        self._group_aliases = _aliases("group", group_aliases)
        self._scene_aliases = _aliases("scene", scene_aliases)
        self._schedule_aliases = _aliases("schedule", schedule_aliases)
        self._capability_snapshot = capability_snapshot
        self._clock = clock

    def scene_run(self, *, group_alias: str, scene_alias: str) -> SmartLedzDryRun:
        group_id = self._resolve(self._group_aliases, group_alias, "group")
        scene_id = self._resolve(self._scene_aliases, scene_alias, "scene")
        snapshot = self._capability_snapshot
        if snapshot is None:
            return self._stopped(
                group_alias,
                DryRunSupport.INDETERMINATE,
                "runtime_capability_missing",
            )
        evaluated_at = self._clock()
        _aware("clock result", evaluated_at)
        if snapshot.gateway_id != self._gateway_id:
            return self._stopped(
                group_alias,
                DryRunSupport.INDETERMINATE,
                "runtime_capability_target_mismatch",
            )
        if snapshot.quality is not Quality.GOOD:
            return self._stopped(
                group_alias,
                DryRunSupport.INDETERMINATE,
                "runtime_capability_quality_insufficient",
            )
        if not snapshot.is_fresh_at(evaluated_at):
            return self._stopped(
                group_alias,
                DryRunSupport.INDETERMINATE,
                "runtime_capability_stale",
            )
        if not snapshot.scene_run_supported:
            return self._stopped(
                group_alias,
                DryRunSupport.UNSUPPORTED,
                "scene_run_not_advertised",
            )
        if not snapshot.scene_readback_supported:
            return self._stopped(
                group_alias,
                DryRunSupport.INDETERMINATE,
                "scene_readback_not_supported",
            )
        if scene_alias not in snapshot.group_scenes.get(group_alias, frozenset()):
            return self._stopped(
                group_alias,
                DryRunSupport.UNSUPPORTED,
                "scene_not_observed_for_group",
            )
        return SmartLedzDryRun(
            SmartLedzOperation.SCENE_RUN,
            group_alias,
            DryRunSupport.VERIFIED,
            "verified_command_shape_dry_run_only",
            {
                "c": "GroupSceneRun",
                "gateway_id": self._gateway_id,
                "group_id": group_id,
                "scene_id": scene_id,
            },
        )

    @staticmethod
    def _stopped(
        group_alias: str,
        support: DryRunSupport,
        reason: str,
    ) -> SmartLedzDryRun:
        return SmartLedzDryRun(
            SmartLedzOperation.SCENE_RUN,
            group_alias,
            support,
            reason,
        )

    def schedule_select(
        self, *, group_alias: str, schedule_alias: str
    ) -> SmartLedzDryRun:
        self._resolve(self._group_aliases, group_alias, "group")
        self._resolve(self._schedule_aliases, schedule_alias, "schedule")
        return SmartLedzDryRun(
            SmartLedzOperation.SCHEDULE_SELECT,
            group_alias,
            DryRunSupport.UNSUPPORTED,
            "schedule_selection_schema_and_readback_unverified",
        )

    @staticmethod
    def _resolve(values: Mapping[str, int], alias: str, kind: str) -> int:
        _alias(alias)
        try:
            return values[alias]
        except KeyError as error:
            raise PermissionError(f"{kind} alias is not configured") from error


def _identifier(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"{name} is out of range")
    return value


def _alias(value: str) -> str:
    if not isinstance(value, str) or _SAFE_ALIAS.fullmatch(value) is None:
        raise ValueError("alias must be a safe opaque reference")
    return value


def _aliases(name: str, values: Mapping[str, int]) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for alias, source_id in values.items():
        normalized[_alias(alias)] = _identifier(f"{name}_id", source_id)
    return normalized


def _aware(name: str, value: datetime) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
