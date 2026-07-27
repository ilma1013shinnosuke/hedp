"""Strict parser for manually captured facts from official publications.

The upstream HTML/PDF layouts are not treated as stable APIs.  A fetch/extract
step must create the small JSON contract parsed here while preserving the
original response separately as Raw.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any
from urllib.parse import urlparse

from hedp.observations import Quality

from .models import (
    Applicability,
    ComponentKind,
    EligibilityRule,
    OfficialDocument,
    RawOfficialPayload,
    RevisionStatus,
    TariffDataset,
    TariffPlan,
    TariffRate,
)

_OFFICIAL_HOSTS = {
    "www.rikuden.co.jp",
    "rikuden.co.jp",
    "www.enecho.meti.go.jp",
    "enecho.meti.go.jp",
}


class TariffParseError(ValueError):
    pass


def parse_official_payload(
    payload: bytes,
    *,
    source_url: str,
    fetched_at: datetime,
    content_type: str = "application/json",
) -> TariffDataset:
    _require_official_url(source_url)
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise TariffParseError("fetched_at must include a UTC offset")
    try:
        root = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TariffParseError("payload must be valid UTF-8 JSON") from exc
    if not isinstance(root, dict) or root.get("schema_version") != 1:
        raise TariffParseError("unsupported tariff extraction schema")
    if root.get("fixture_anonymized") not in {True, False}:
        raise TariffParseError("fixture_anonymized must be explicit")

    raw = RawOfficialPayload(
        source_url=source_url,
        fetched_at=fetched_at,
        content_type=content_type,
        sha256=hashlib.sha256(payload).hexdigest(),
        payload=payload,
    )
    documents = tuple(_parse_document(item) for item in _items(root, "documents"))
    document_ids = {item.source_id for item in documents}
    if len(document_ids) != len(documents):
        raise TariffParseError("document source_id must be unique")
    plans = tuple(_parse_plan(item, document_ids) for item in _items(root, "plans"))
    plan_ids = {item.plan_id for item in plans}
    if len(plan_ids) != len(plans):
        raise TariffParseError("plan_id must be unique")
    rates = tuple(
        _parse_rate(item, document_ids, plan_ids) for item in _items(root, "rates")
    )
    if len({item.rate_id for item in rates}) != len(rates):
        raise TariffParseError("rate_id must be unique")
    return TariffDataset(raw=raw, documents=documents, plans=plans, rates=rates)


def _items(root: dict[str, Any], name: str) -> list[dict[str, Any]]:
    value = root.get(name)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise TariffParseError(f"{name} must be an object array")
    return value


def _parse_document(item: dict[str, Any]) -> OfficialDocument:
    url = _required_text(item, "source_url")
    _require_official_url(url)
    return OfficialDocument(
        source_id=_required_text(item, "source_id"),
        publisher=_required_text(item, "publisher"),
        source_url=url,
        announced_on=_required_date(item, "announced_on"),
        effective_from=_optional_date(item, "effective_from"),
        effective_until=_optional_date(item, "effective_until"),
        status=_enum(RevisionStatus, item, "status"),
        replaces_source_id=_optional_text(item, "replaces_source_id"),
        quality=_enum(Quality, item, "quality"),
    )


def _parse_plan(item: dict[str, Any], document_ids: set[str]) -> TariffPlan:
    source_id = _required_text(item, "source_id")
    _require_reference(source_id, document_ids, "plan source_id")
    rules_value = item.get("eligibility")
    if not isinstance(rules_value, list):
        raise TariffParseError("eligibility must be an array")
    rules = tuple(
        EligibilityRule(
            rule_code=_required_text(rule, "rule_code"),
            description=_required_text(rule, "description"),
            required=_required_bool(rule, "required"),
            quality=_enum(Quality, rule, "quality"),
        )
        for rule in rules_value
        if isinstance(rule, dict)
    )
    if len(rules) != len(rules_value):
        raise TariffParseError("eligibility entries must be objects")
    return TariffPlan(
        plan_id=_required_text(item, "plan_id"),
        display_name=_required_text(item, "display_name"),
        service_area=_required_text(item, "service_area"),
        regulatory_class=_required_text(item, "regulatory_class"),
        enrollment_status=_required_text(item, "enrollment_status"),
        applicability=_enum(Applicability, item, "applicability"),
        eligibility=rules,
        eligibility_complete=_required_bool(item, "eligibility_complete"),
        effective_from=_optional_date(item, "effective_from"),
        effective_until=_optional_date(item, "effective_until"),
        status=_enum(RevisionStatus, item, "status"),
        source_id=source_id,
        quality=_enum(Quality, item, "quality"),
    )


def _parse_rate(
    item: dict[str, Any],
    document_ids: set[str],
    plan_ids: set[str],
) -> TariffRate:
    source_id = _required_text(item, "source_id")
    _require_reference(source_id, document_ids, "rate source_id")
    plan_id = _optional_text(item, "plan_id")
    if plan_id is not None:
        _require_reference(plan_id, plan_ids, "rate plan_id")
    quality = _enum(Quality, item, "quality")
    value = _optional_decimal(item, "value")
    if quality in {Quality.MISSING, Quality.INVALID, Quality.UNKNOWN} and value is not None:
        raise TariffParseError(f"{quality.value} rate value must be null")
    if quality in {Quality.GOOD, Quality.STALE, Quality.ESTIMATED} and value is None:
        raise TariffParseError(f"{quality.value} rate value must not be null")
    reason = _optional_text(item, "reason")
    if value is None and reason is None:
        raise TariffParseError("absent rate value requires reason")
    return TariffRate(
        rate_id=_required_text(item, "rate_id"),
        plan_id=plan_id,
        component=_enum(ComponentKind, item, "component"),
        label=_required_text(item, "label"),
        value=value,
        unit=_optional_text(item, "unit"),
        tier_from=_optional_decimal(item, "tier_from"),
        tier_until=_optional_decimal(item, "tier_until"),
        time_window=_optional_text(item, "time_window"),
        season=_optional_text(item, "season"),
        applicability=_enum(Applicability, item, "applicability"),
        effective_from=_optional_date(item, "effective_from"),
        effective_until=_optional_date(item, "effective_until"),
        status=_enum(RevisionStatus, item, "status"),
        source_id=source_id,
        quality=quality,
        reason=reason,
    )


def _require_official_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in _OFFICIAL_HOSTS:
        raise TariffParseError("source_url must be an approved official HTTPS source")


def _required_text(item: dict[str, Any], name: str) -> str:
    value = item.get(name)
    if not isinstance(value, str) or not value.strip():
        raise TariffParseError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_text(item: dict[str, Any], name: str) -> str | None:
    value = item.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise TariffParseError(f"{name} must be null or a non-empty string")
    return value.strip()


def _required_bool(item: dict[str, Any], name: str) -> bool:
    value = item.get(name)
    if not isinstance(value, bool):
        raise TariffParseError(f"{name} must be boolean")
    return value


def _required_date(item: dict[str, Any], name: str) -> date:
    value = _optional_date(item, name)
    if value is None:
        raise TariffParseError(f"{name} must be an ISO date")
    return value


def _optional_date(item: dict[str, Any], name: str) -> date | None:
    value = item.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TariffParseError(f"{name} must be null or an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise TariffParseError(f"{name} must be null or an ISO date") from exc


def _optional_decimal(item: dict[str, Any], name: str) -> Decimal | None:
    value = item.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TariffParseError(f"{name} must be a decimal string or null")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise TariffParseError(f"{name} must be a decimal string or null") from exc


def _enum(enum_type: type[Enum], item: dict[str, Any], name: str) -> Any:
    value = item.get(name)
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise TariffParseError(f"{name} has an unsupported value") from exc


def _require_reference(value: str, allowed: set[str], name: str) -> None:
    if value not in allowed:
        raise TariffParseError(f"{name} references an unknown item")
