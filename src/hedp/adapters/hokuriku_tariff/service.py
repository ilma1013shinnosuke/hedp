"""Ingestion, diff, freshness, and public-candidate eligibility services."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Any

from .models import Applicability, PersonalEligibility, TariffDataset
from .storage import OfflineTariffRepository, _json_default


class TariffIngestionService:
    def __init__(
        self,
        repository: OfflineTariffRepository,
        *,
        update_interval: timedelta = timedelta(hours=24),
        stale_after: timedelta = timedelta(hours=48),
    ) -> None:
        if update_interval <= timedelta(0) or stale_after <= timedelta(0):
            raise ValueError("update and stale intervals must be positive")
        self.repository = repository
        self.update_interval = update_interval
        self.stale_after = stale_after

    def is_update_due(self, *, now: datetime) -> bool:
        latest = self.repository.latest_fetch_at()
        return latest is None or now - latest >= self.update_interval

    def is_stale(self, *, now: datetime) -> bool:
        latest = self.repository.latest_fetch_at()
        return latest is None or now - latest > self.stale_after

    def diff(
        self,
        dataset: TariffDataset,
        *,
        as_of: date,
    ) -> dict[str, dict[str, tuple[str, ...]]]:
        result: dict[str, dict[str, tuple[str, ...]]] = {}
        for kind, entities in (("plan", dataset.plans), ("rate", dataset.rates)):
            previous = self.repository.current(kind, as_of=as_of)
            incoming = {
                entity.entity_key: _canonical_dict(asdict(entity)) for entity in entities
            }
            previous_keys = set(previous)
            incoming_keys = set(incoming)
            result[kind] = {
                "added": tuple(sorted(incoming_keys - previous_keys)),
                "changed": tuple(
                    sorted(
                        key
                        for key in incoming_keys & previous_keys
                        if incoming[key] != previous[key]
                    )
                ),
                # An omission is evidence for review, never an implicit cancellation.
                "omitted": tuple(sorted(previous_keys - incoming_keys)),
            }
        return result

    def ingest(
        self,
        dataset: TariffDataset,
        *,
        recorded_at: datetime,
    ) -> dict[str, Any]:
        changes = self.diff(dataset, as_of=recorded_at.date())
        inserted = self.repository.ingest(dataset, recorded_at=recorded_at)
        return {"inserted_revisions": inserted, "changes": changes}

    @staticmethod
    def assess_personal_eligibility(
        plan_id: str,
        *,
        evaluated_at: datetime,
        household_contract: dict[str, object] | None = None,
    ) -> PersonalEligibility:
        if not household_contract:
            return PersonalEligibility(
                plan_id=plan_id,
                applicability=Applicability.UNKNOWN,
                reason="household_contract_not_configured",
                evaluated_at=evaluated_at,
            )
        return PersonalEligibility(
            plan_id=plan_id,
            applicability=Applicability.UNKNOWN,
            reason="plan_specific_evaluator_not_implemented",
            evaluated_at=evaluated_at,
        )


def _canonical_dict(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default)
    )
