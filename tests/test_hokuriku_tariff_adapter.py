from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from hedp.adapters.hokuriku_tariff import (
    Applicability,
    OfflineTariffRepository,
    TariffIngestionService,
    TariffParseError,
    parse_official_payload,
)
from hedp.adapters.hokuriku_tariff.collector import (
    CollectionLimits,
    HokurikuTariffCollector,
)
from hedp.observations import Quality


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "hokuriku_tariff"
    / "official_household_snapshot_anonymous.json"
)
FETCHED_AT = datetime(2026, 7, 27, 6, 0, tzinfo=timezone.utc)
SOURCE_URL = "https://www.rikuden.co.jp/ryokin/minsei.html"


def _payload() -> bytes:
    return FIXTURE.read_bytes()


def _dataset(payload: bytes | None = None):
    return parse_official_payload(
        _payload() if payload is None else payload,
        source_url=SOURCE_URL,
        fetched_at=FETCHED_AT,
    )


def test_parser_keeps_public_candidates_separate_from_personal_eligibility() -> None:
    dataset = _dataset()
    assert {plan.display_name for plan in dataset.plans} == {
        "使っておとくライト",
        "従量電灯ネクスト",
        "くつろぎナイト12",
        "節電とくとく電灯",
        "ecoシフトチェンジ",
        "従量電灯",
        "アクアECOプラン",
        "エルフナイト8",
        "エルフナイト10",
        "エルフナイト10プラス",
        "深夜電力",
    }
    assert all(
        plan.applicability is Applicability.PUBLIC_CANDIDATE for plan in dataset.plans
    )
    assert all(not plan.eligibility_complete for plan in dataset.plans)
    assert {
        plan.display_name
        for plan in dataset.plans
        if plan.enrollment_status == "closed_to_new_enrollment"
    } == {
        "エルフナイト8",
        "エルフナイト10",
        "エルフナイト10プラス",
        "深夜電力",
    }
    result = TariffIngestionService.assess_personal_eligibility(
        "kutsurogi-night-12",
        evaluated_at=FETCHED_AT,
    )
    assert result.applicability is Applicability.UNKNOWN
    assert result.reason == "household_contract_not_configured"


def test_parser_preserves_decimal_and_explicit_missing_unknown() -> None:
    dataset = _dataset()
    rates = {rate.rate_id: rate for rate in dataset.rates}
    assert rates["fixture-energy-tier-1"].value == Decimal("12.34")
    assert rates["fixture-fuel-adjustment"].value is None
    assert rates["fixture-fuel-adjustment"].quality is Quality.MISSING
    assert rates["fixture-market-adjustment"].value is None
    assert rates["fixture-market-adjustment"].quality is Quality.UNKNOWN


@pytest.mark.parametrize(
    "url",
    [
        "http://www.rikuden.co.jp/ryokin/minsei.html",
        "https://example.com/copied-tariff",
    ],
)
def test_parser_rejects_nonofficial_or_non_https_source(url: str) -> None:
    with pytest.raises(TariffParseError, match="official HTTPS"):
        parse_official_payload(_payload(), source_url=url, fetched_at=FETCHED_AT)


def test_parser_rejects_good_null_value_instead_of_inventing_zero() -> None:
    root = json.loads(_payload())
    root["rates"][0]["value"] = None
    with pytest.raises(TariffParseError, match="good rate value"):
        _dataset(json.dumps(root).encode())


def test_parser_requires_explicit_eligibility_completeness() -> None:
    root = json.loads(_payload())
    del root["plans"][0]["eligibility_complete"]
    with pytest.raises(TariffParseError, match="eligibility_complete"):
        _dataset(json.dumps(root, ensure_ascii=False).encode())


def test_raw_round_trip_is_byte_exact_and_hash_deduplicated(tmp_path: Path) -> None:
    dataset = _dataset()
    path = tmp_path / "rates.tariff-test.sqlite3"
    with OfflineTariffRepository(path) as repository:
        first = repository.ingest(dataset, recorded_at=FETCHED_AT)
        second = repository.ingest(dataset, recorded_at=FETCHED_AT + timedelta(minutes=1))
        assert first > 0
        assert second == 0
        assert repository.raw_payload(dataset.raw.sha256) == _payload()


def test_current_and_history_are_separate_and_correction_is_append_only(
    tmp_path: Path,
) -> None:
    root = json.loads(_payload())
    path = tmp_path / "rates.tariff-test.sqlite3"
    with OfflineTariffRepository(path) as repository:
        service = TariffIngestionService(repository)
        service.ingest(_dataset(), recorded_at=FETCHED_AT)
        root["rates"][0]["value"] = "124.00"
        root["rates"][0]["status"] = "corrected"
        root["documents"][0]["status"] = "corrected"
        corrected = _dataset(json.dumps(root, ensure_ascii=False).encode())
        service.ingest(corrected, recorded_at=FETCHED_AT + timedelta(hours=1))

        history = repository.history("rate", "fixture-basic-monthly")
        current = repository.current("rate", as_of=date(2026, 7, 27))
        assert [row["value"] for row in history] == ["123.45", "124.00"]
        assert current["fixture-basic-monthly"]["value"] == "124.00"


def test_future_announced_rate_is_stored_but_not_current_early(tmp_path: Path) -> None:
    root = json.loads(_payload())
    root["rates"][0]["effective_from"] = "2027-01-01"
    dataset = _dataset(json.dumps(root, ensure_ascii=False).encode())
    with OfflineTariffRepository(
        tmp_path / "future.tariff-test.sqlite3"
    ) as repository:
        repository.ingest(dataset, recorded_at=FETCHED_AT)
        current = repository.current("rate", as_of=date(2026, 7, 27))
        future = repository.future("rate", after=date(2026, 7, 27))
        assert "fixture-basic-monthly" not in current
        assert any(row["rate_id"] == "fixture-basic-monthly" for row in future)


def test_explicit_cancellation_is_appended_and_removed_from_current(
    tmp_path: Path,
) -> None:
    root = json.loads(_payload())
    path = tmp_path / "cancelled.tariff-test.sqlite3"
    with OfflineTariffRepository(path) as repository:
        repository.ingest(_dataset(), recorded_at=FETCHED_AT)
        root["rates"][0]["status"] = "cancelled"
        root["rates"][0]["effective_from"] = "2026-08-01"
        cancelled = _dataset(json.dumps(root, ensure_ascii=False).encode())
        repository.ingest(
            cancelled,
            recorded_at=FETCHED_AT + timedelta(hours=1),
        )

        assert len(repository.history("rate", "fixture-basic-monthly")) == 2
        assert "fixture-basic-monthly" in repository.current(
            "rate", as_of=date(2026, 7, 31)
        )
        assert "fixture-basic-monthly" not in repository.current(
            "rate", as_of=date(2026, 8, 1)
        )


def test_omission_is_reported_but_never_implicitly_cancelled(tmp_path: Path) -> None:
    with OfflineTariffRepository(
        tmp_path / "diff.tariff-test.sqlite3"
    ) as repository:
        service = TariffIngestionService(repository)
        service.ingest(_dataset(), recorded_at=FETCHED_AT)
        root = json.loads(_payload())
        root["rates"] = root["rates"][:-1]
        changes = service.diff(
            _dataset(json.dumps(root, ensure_ascii=False).encode()),
            as_of=FETCHED_AT.date(),
        )
        assert changes["rate"]["omitted"] == ("fixture-government-support-july",)
        assert (
            "fixture-government-support-july"
            in repository.current("rate", as_of=FETCHED_AT.date())
        )


def test_update_due_and_stale_have_independent_thresholds(tmp_path: Path) -> None:
    with OfflineTariffRepository(
        tmp_path / "freshness.tariff-test.sqlite3"
    ) as repository:
        service = TariffIngestionService(
            repository,
            update_interval=timedelta(hours=24),
            stale_after=timedelta(hours=48),
        )
        assert service.is_update_due(now=FETCHED_AT)
        assert service.is_stale(now=FETCHED_AT)
        repository.ingest(_dataset(), recorded_at=FETCHED_AT)
        assert service.is_update_due(now=FETCHED_AT + timedelta(hours=25))
        assert not service.is_stale(now=FETCHED_AT + timedelta(hours=25))
        assert service.is_stale(now=FETCHED_AT + timedelta(hours=49))


def test_offline_repository_refuses_normal_or_production_db_names(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="tariff-test"):
        OfflineTariffRepository(tmp_path / "hedp.db")


def test_bounded_collector_enforces_byte_limit() -> None:
    class Fetcher:
        def fetch(self, *, timeout_seconds: float, max_bytes: int):
            assert timeout_seconds == 1.0
            assert max_bytes == 10
            return SOURCE_URL, b"x" * 11

    collector = HokurikuTariffCollector(
        Fetcher(), limits=CollectionLimits(timeout_seconds=1.0, max_bytes=10)
    )
    with pytest.raises(ValueError, match="byte limit"):
        collector.collect_once(fetched_at=FETCHED_AT)
