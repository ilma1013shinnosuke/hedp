"""Offline ingestion contracts for official Hokuriku household tariffs."""

from .models import (
    Applicability,
    ComponentKind,
    EligibilityRule,
    OfficialDocument,
    PersonalEligibility,
    RawOfficialPayload,
    RevisionStatus,
    TariffDataset,
    TariffPlan,
    TariffRate,
)
from .parser import TariffParseError, parse_official_payload
from .service import TariffIngestionService
from .storage import OfflineTariffRepository

__all__ = [
    "Applicability",
    "ComponentKind",
    "EligibilityRule",
    "OfficialDocument",
    "OfflineTariffRepository",
    "PersonalEligibility",
    "RawOfficialPayload",
    "RevisionStatus",
    "TariffDataset",
    "TariffIngestionService",
    "TariffParseError",
    "TariffPlan",
    "TariffRate",
    "parse_official_payload",
]
