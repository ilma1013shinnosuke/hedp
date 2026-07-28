from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hedp.adapters.hokuriku_tariff import parse_official_payload
from hedp.adapters.hokuriku_tariff.collector import HokurikuTariffCollector
from hedp.integrations.kura import (
    DeliveryCommitRecord,
    DurableKuraInbox,
    ReceiverPolicy,
    build_shadow_observation,
    canonical_envelope_sha256,
    compare_shadow,
    parse_delivery_json,
    validate_delivery_json,
)
from hedp.integrations.kura.inbox import InboxCommitError


NOW = datetime(2030, 1, 15, 12, 0, tzinfo=UTC)
RAW = b"%PDF-1.4\n% HESTIA synthetic public fixture\n%%EOF\n"


def _policy(
    *,
    source_id: str = "synthetic-hestia-public",
    media_type: str = "application/pdf",
) -> ReceiverPolicy:
    return ReceiverPolicy(
        recipient="hestia",
        allowed_purposes=frozenset({"shadow_evaluation"}),
        allowed_source_ids=frozenset({source_id}),
        allowed_connector_release_ids=frozenset({"public-pdf-v1"}),
        allowed_media_types=frozenset({media_type}),
    )


def _envelope(
    raw: bytes = RAW,
    *,
    source_id: str = "synthetic-hestia-public",
    media_type: str = "application/pdf",
) -> dict[str, object]:
    return {
        "protocol_version": "kura.delivery/1",
        "delivery": {
            "id": "delivery-hestia-1",
            "recipient": "hestia",
            "purpose": "shadow_evaluation",
            "created_at": "2030-01-15T11:00:00Z",
            "expires_at": "2030-01-16T12:00:00Z",
        },
        "source": {
            "id": source_id,
            "contract": {"contract_version": "kura.source/1"},
        },
        "connector": {
            "release_id": "public-pdf-v1",
            "id": "public-pdf",
            "version": "1.0.0",
            "code_sha256": "1" * 64,
            "contract_version": "kura.collector/1",
        },
        "collection": {
            "id": "collection-1",
            "mode": "shadow",
            "request_fingerprint": "2" * 64,
            "item_count": 1,
        },
        "receipt": {
            "id": "receipt-1",
            "kind": "fetched",
            "checked_at": "2030-01-15T11:00:00Z",
            "rights": {},
        },
        "artifact": {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "raw_size": len(raw),
            "media_type": media_type,
        },
    }


def _encoded(envelope: dict[str, object]) -> bytes:
    return (
        json.dumps(
            envelope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def test_safe_entry_rejects_invalid_utf8_nonobject_and_duplicate_keys() -> None:
    for value in (
        b"\xff",
        b"[]",
        b'{"delivery":{"id":"one","id":"two"}}',
    ):
        result = validate_delivery_json(
            value,
            RAW,
            "0" * 64,
            _policy(),
            now=NOW,
        )
        assert result.code == "INVALID_ENVELOPE"
        assert not result.requires_commit
        assert not result.requires_ack


def test_inbox_returns_ack_only_after_durable_commit(tmp_path: Path) -> None:
    envelope = _envelope()
    envelope_hash = canonical_envelope_sha256(envelope)
    path = tmp_path / "public.kura-inbox.sqlite3"
    with DurableKuraInbox(path) as inbox:
        outcome = inbox.receive(
            raw=RAW,
            envelope_json=_encoded(envelope),
            provided_envelope_sha256=envelope_hash,
            policy=_policy(),
            evaluated_at=NOW,
        )
        assert outcome.committed
        assert outcome.acknowledgement is not None
        assert inbox.raw_payload("delivery-hestia-1") == RAW
        assert inbox.delivery_count() == 1
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_duplicate_is_not_recommitted_or_reacknowledged(tmp_path: Path) -> None:
    envelope = _envelope()
    envelope_hash = canonical_envelope_sha256(envelope)
    with DurableKuraInbox(tmp_path / "public.kura-inbox.sqlite3") as inbox:
        first = inbox.receive(
            raw=RAW,
            envelope_json=_encoded(envelope),
            provided_envelope_sha256=envelope_hash,
            policy=_policy(),
            evaluated_at=NOW,
        )
        second = inbox.receive(
            raw=RAW,
            envelope_json=_encoded(envelope),
            provided_envelope_sha256=envelope_hash,
            policy=_policy(),
            evaluated_at=NOW,
        )
        assert first.acknowledgement is not None
        assert second.conformance.code == "DUPLICATE_DELIVERY"
        assert not second.committed
        assert second.acknowledgement is None
        assert inbox.delivery_count() == 1


def test_same_delivery_id_with_changed_binding_is_rejected(tmp_path: Path) -> None:
    envelope = _envelope()
    with DurableKuraInbox(tmp_path / "public.kura-inbox.sqlite3") as inbox:
        inbox.receive(
            raw=RAW,
            envelope_json=_encoded(envelope),
            provided_envelope_sha256=canonical_envelope_sha256(envelope),
            policy=_policy(),
            evaluated_at=NOW,
        )
        changed = deepcopy(envelope)
        changed_raw = b"0" * len(RAW)
        changed["artifact"]["sha256"] = hashlib.sha256(  # type: ignore[index]
            changed_raw
        ).hexdigest()
        changed["artifact"]["raw_size"] = len(RAW)  # type: ignore[index]
        outcome = inbox.receive(
            raw=changed_raw,
            envelope_json=_encoded(changed),
            provided_envelope_sha256=canonical_envelope_sha256(changed),
            policy=_policy(),
            evaluated_at=NOW,
        )
        assert outcome.conformance.code == "DELIVERY_ID_CONFLICT"
        assert not outcome.committed
        assert outcome.acknowledgement is None


def test_commit_failure_cannot_expose_ack(tmp_path: Path) -> None:
    envelope = _envelope()
    inbox = DurableKuraInbox(tmp_path / "public.kura-inbox.sqlite3")
    inbox._connection.execute(  # noqa: SLF001 - deliberate failure injection
        """
        CREATE TRIGGER refuse_kura_commit
        BEFORE INSERT ON kura_inbox
        BEGIN
            SELECT RAISE(ABORT, 'fixture refusal');
        END
        """
    )
    with pytest.raises(InboxCommitError):
        inbox.receive(
            raw=RAW,
            envelope_json=_encoded(envelope),
            provided_envelope_sha256=canonical_envelope_sha256(envelope),
            policy=_policy(),
            evaluated_at=NOW,
        )
    assert inbox.delivery_count() == 0
    inbox.close()


def test_rejected_delivery_never_changes_inbox(tmp_path: Path) -> None:
    envelope = _envelope()
    envelope["delivery"]["recipient"] = "other"  # type: ignore[index]
    with DurableKuraInbox(tmp_path / "public.kura-inbox.sqlite3") as inbox:
        outcome = inbox.receive(
            raw=RAW,
            envelope_json=_encoded(envelope),
            provided_envelope_sha256=canonical_envelope_sha256(envelope),
            policy=_policy(),
            evaluated_at=NOW,
        )
        assert outcome.conformance.code == "RECIPIENT_MISMATCH"
        assert not outcome.committed
        assert outcome.acknowledgement is None
        assert inbox.delivery_count() == 0


class _FixtureFetcher:
    def __init__(self, source_url: str, payload: bytes) -> None:
        self.source_url = source_url
        self.payload = payload

    def fetch(self, *, timeout_seconds: float, max_bytes: int) -> tuple[str, bytes]:
        assert timeout_seconds > 0
        assert len(self.payload) <= max_bytes
        return self.source_url, self.payload


def _formatted_tariff(dataset: object) -> list[dict[str, object]]:
    plans = getattr(dataset, "plans")
    rates = getattr(dataset, "rates")
    documents = getattr(dataset, "documents")
    return [
        {"kind": "document", "id": item.source_id} for item in documents
    ] + [
        {"kind": "plan", "id": item.plan_id, "status": item.status.value}
        for item in plans
    ] + [
        {
            "kind": "rate",
            "id": item.rate_id,
            "value": None if item.value is None else str(item.value),
            "quality": item.quality.value,
        }
        for item in rates
    ]


def test_real_existing_collector_matches_kura_delivered_raw(tmp_path: Path) -> None:
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "hokuriku_tariff"
        / "official_household_snapshot_anonymous.json"
    )
    raw = fixture.read_bytes()
    fetched_at = datetime(2026, 7, 27, 6, 0, tzinfo=UTC)
    source_url = "https://www.rikuden.co.jp/ryokin/minsei.html"
    baseline_dataset = HokurikuTariffCollector(
        _FixtureFetcher(source_url, raw)
    ).collect_once(fetched_at=fetched_at)

    envelope = _envelope(
        raw,
        source_id="hokuriku-official-tariff",
        media_type="application/json",
    )
    with DurableKuraInbox(tmp_path / "tariff.kura-inbox.sqlite3") as inbox:
        outcome = inbox.receive(
            raw=raw,
            envelope_json=_encoded(envelope),
            provided_envelope_sha256=canonical_envelope_sha256(envelope),
            policy=_policy(
                source_id="hokuriku-official-tariff",
                media_type="application/json",
            ),
            evaluated_at=NOW,
        )
        assert outcome.committed
        candidate_raw = inbox.raw_payload("delivery-hestia-1")
    assert candidate_raw is not None
    candidate_dataset = parse_official_payload(
        candidate_raw,
        source_url=source_url,
        fetched_at=fetched_at,
    )
    checked_at = datetime(2026, 7, 27, 6, 1, tzinfo=UTC)
    baseline = build_shadow_observation(
        app_id="hestia-baseline",
        source_id="hokuriku-official-tariff",
        raw=baseline_dataset.raw.payload,
        retrieved_at=baseline_dataset.raw.fetched_at,
        checked_at=checked_at,
        formatted_records=_formatted_tariff(baseline_dataset),
    )
    candidate = build_shadow_observation(
        app_id="hestia-baseline",
        source_id="hokuriku-official-tariff",
        raw=candidate_raw,
        retrieved_at=candidate_dataset.raw.fetched_at,
        checked_at=checked_at,
        formatted_records=_formatted_tariff(candidate_dataset),
    )
    result = compare_shadow(baseline, candidate)
    assert result["status"] == "match"
    assert result["differences"] == []


def test_kura_unavailable_does_not_break_existing_collector(tmp_path: Path) -> None:
    unavailable_parent = tmp_path / "not-a-directory"
    unavailable_parent.write_bytes(b"occupied")
    with pytest.raises(OSError):
        DurableKuraInbox(unavailable_parent / "x.kura-inbox.sqlite3")

    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "hokuriku_tariff"
        / "official_household_snapshot_anonymous.json"
    )
    dataset = HokurikuTariffCollector(
        _FixtureFetcher(
            "https://www.rikuden.co.jp/ryokin/minsei.html",
            fixture.read_bytes(),
        )
    ).collect_once(fetched_at=datetime(2026, 7, 27, 6, 0, tzinfo=UTC))
    assert dataset.plans


@pytest.mark.skipif(
    "KURA_RECEIVER_FIXTURE_ROOT" not in os.environ,
    reason="canonical KURA fixture path is supplied only for conformance runs",
)
def test_canonical_kura_language_independent_fixture() -> None:
    fixture_root = Path(os.environ["KURA_RECEIVER_FIXTURE_ROOT"])
    manifest = json.loads((fixture_root / "manifest.json").read_text("utf-8"))
    evaluation_time = datetime.fromisoformat(
        manifest["evaluation_time"].replace("Z", "+00:00")
    )
    for case in manifest["cases"]:
        profile = manifest["receiver_profiles"][case["receiver_profile"]]
        policy = ReceiverPolicy(
            recipient=profile["recipient"],
            allowed_purposes=frozenset(profile["allowed_purposes"]),
            allowed_source_ids=frozenset(profile["allowed_source_ids"]),
            allowed_connector_release_ids=frozenset(
                profile["allowed_connector_release_ids"]
            ),
            allowed_media_types=frozenset(profile["allowed_media_types"]),
        )
        envelope = parse_delivery_json(
            (fixture_root / case["envelope_template"]).read_bytes()
        )
        for patch in case["envelope_patches"]:
            assert patch["op"] == "replace"
            target = envelope
            parts = [
                part.replace("~1", "/").replace("~0", "~")
                for part in patch["path"].lstrip("/").split("/")
            ]
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = patch["value"]

        raw = (fixture_root / case["raw_file"]).read_bytes()
        committed = {}
        for delivery_id, record in case.get("committed_records", {}).items():
            committed[delivery_id] = DeliveryCommitRecord(**record)
        for expected in case["expected"]:
            result = validate_delivery_json(
                _encoded(envelope),
                raw,
                case["provided_envelope_sha256"],
                policy,
                committed_delivery_records=committed,
                now=evaluation_time,
            )
            assert result.code == expected["code"], case["id"]
            assert (
                result.requires_commit == expected["new_inbox_commit_required"]
            ), case["id"]
            assert result.requires_ack == expected["ack_required"], case["id"]
            if result.accepted:
                assert result.delivery_id is not None
                assert result.commit_record is not None
                committed[result.delivery_id] = result.commit_record
