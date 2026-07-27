"""Typed, append-only facts extracted from official tariff publications."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from hedp.observations import Quality


class RevisionStatus(str, Enum):
    ANNOUNCED = "announced"
    CORRECTED = "corrected"
    CANCELLED = "cancelled"


class Applicability(str, Enum):
    PUBLIC_CANDIDATE = "public_candidate"
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class ComponentKind(str, Enum):
    BASIC_CHARGE = "basic_charge"
    ENERGY_RATE = "energy_rate"
    FUEL_ADJUSTMENT = "fuel_adjustment"
    MARKET_ADJUSTMENT = "market_adjustment"
    RENEWABLE_SURCHARGE = "renewable_surcharge"
    GOVERNMENT_SUBSIDY = "government_subsidy"


@dataclass(frozen=True)
class RawOfficialPayload:
    source_url: str
    fetched_at: datetime
    content_type: str
    sha256: str
    payload: bytes


@dataclass(frozen=True)
class OfficialDocument:
    source_id: str
    publisher: str
    source_url: str
    announced_on: date
    effective_from: date | None
    effective_until: date | None
    status: RevisionStatus
    replaces_source_id: str | None
    quality: Quality


@dataclass(frozen=True)
class EligibilityRule:
    rule_code: str
    description: str
    required: bool
    quality: Quality


@dataclass(frozen=True)
class TariffPlan:
    plan_id: str
    display_name: str
    service_area: str
    regulatory_class: str
    enrollment_status: str
    applicability: Applicability
    eligibility: tuple[EligibilityRule, ...]
    eligibility_complete: bool
    effective_from: date | None
    effective_until: date | None
    status: RevisionStatus
    source_id: str
    quality: Quality

    @property
    def entity_key(self) -> str:
        return self.plan_id


@dataclass(frozen=True)
class TariffRate:
    rate_id: str
    plan_id: str | None
    component: ComponentKind
    label: str
    value: Decimal | None
    unit: str | None
    tier_from: Decimal | None
    tier_until: Decimal | None
    time_window: str | None
    season: str | None
    applicability: Applicability
    effective_from: date | None
    effective_until: date | None
    status: RevisionStatus
    source_id: str
    quality: Quality
    reason: str | None

    @property
    def entity_key(self) -> str:
        return self.rate_id


@dataclass(frozen=True)
class TariffDataset:
    raw: RawOfficialPayload
    documents: tuple[OfficialDocument, ...]
    plans: tuple[TariffPlan, ...]
    rates: tuple[TariffRate, ...]


@dataclass(frozen=True)
class PersonalEligibility:
    """A separate result; public plan discovery never guesses household eligibility."""

    plan_id: str
    applicability: Applicability
    reason: str
    evaluated_at: datetime
