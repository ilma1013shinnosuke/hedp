"""Durable HESTIA-owned Inbox for accepted public KURA deliveries."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .conformance import (
    ConformanceResult,
    DeliveryCommitRecord,
    ReceiverPolicy,
    parse_delivery_json,
    validate_delivery,
)


class InboxCommitError(RuntimeError):
    """A validated delivery could not be made durable."""


@dataclass(frozen=True)
class AcknowledgementIntent:
    """ACK data that exists only after a successful durable commit."""

    delivery_id: str
    recipient: str
    envelope_sha256: str
    raw_sha256: str
    raw_size: int
    committed_at: datetime


@dataclass(frozen=True)
class ReceiveOutcome:
    conformance: ConformanceResult
    committed: bool
    acknowledgement: AcknowledgementIntent | None


class DurableKuraInbox:
    """Separate SQLite Inbox; it must never be pointed at HESTIA's main DB."""

    _EXPECTED_SUFFIX = ".kura-inbox.sqlite3"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.name.endswith(self._EXPECTED_SUFFIX):
            raise ValueError(
                f"KURA Inbox path must end with {self._EXPECTED_SUFFIX}"
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=DELETE")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._initialize()
        if os.name == "posix":
            os.chmod(self.path, 0o600)

    def __enter__(self) -> DurableKuraInbox:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def receive(
        self,
        *,
        raw: bytes,
        envelope_json: bytes | str,
        provided_envelope_sha256: str,
        policy: ReceiverPolicy,
        evaluated_at: datetime | None = None,
    ) -> ReceiveOutcome:
        """Validate, atomically commit, then and only then expose ACK intent."""

        try:
            envelope = parse_delivery_json(envelope_json)
        except ValueError:
            return ReceiveOutcome(
                conformance=ConformanceResult(
                    accepted=False,
                    code="INVALID_ENVELOPE",
                    delivery_id=None,
                ),
                committed=False,
                acknowledgement=None,
            )

        self._connection.execute("BEGIN IMMEDIATE")
        try:
            delivery_id = _untrusted_delivery_id(envelope)
            committed = self._committed_record(delivery_id)
            records = {delivery_id: committed} if delivery_id and committed else {}
            conformance = validate_delivery(
                envelope,
                raw,
                provided_envelope_sha256,
                policy,
                committed_delivery_records=records,
                now=evaluated_at,
            )
            if not conformance.accepted:
                self._connection.rollback()
                return ReceiveOutcome(
                    conformance=conformance,
                    committed=False,
                    acknowledgement=None,
                )
            if (
                conformance.delivery_id is None
                or conformance.commit_record is None
                or not conformance.requires_commit
                or not conformance.requires_ack
            ):
                raise InboxCommitError("accepted delivery lacks commit binding")

            committed_at = datetime.now(UTC)
            delivery = envelope["delivery"]
            source = envelope["source"]
            connector = envelope["connector"]
            artifact = envelope["artifact"]
            assert isinstance(delivery, dict)
            assert isinstance(source, dict)
            assert isinstance(connector, dict)
            assert isinstance(artifact, dict)
            exact_envelope = (
                envelope_json.encode("utf-8")
                if isinstance(envelope_json, str)
                else envelope_json
            )
            self._connection.execute(
                """
                INSERT INTO kura_inbox (
                    delivery_id, recipient, purpose, source_id,
                    connector_release_id, media_type, envelope_sha256,
                    raw_sha256, raw_size, envelope_json, raw, committed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conformance.delivery_id,
                    delivery["recipient"],
                    delivery["purpose"],
                    source["id"],
                    connector["release_id"],
                    artifact["media_type"],
                    provided_envelope_sha256,
                    conformance.commit_record.raw_sha256,
                    conformance.commit_record.raw_size,
                    exact_envelope,
                    raw,
                    committed_at.isoformat(),
                ),
            )
            self._connection.commit()
        except Exception as error:
            self._connection.rollback()
            if isinstance(error, InboxCommitError):
                raise
            raise InboxCommitError("KURA Inbox durable commit failed") from error

        record = conformance.commit_record
        return ReceiveOutcome(
            conformance=conformance,
            committed=True,
            acknowledgement=AcknowledgementIntent(
                delivery_id=conformance.delivery_id,
                recipient=record.recipient,
                envelope_sha256=record.envelope_sha256,
                raw_sha256=record.raw_sha256,
                raw_size=record.raw_size,
                committed_at=committed_at,
            ),
        )

    def raw_payload(self, delivery_id: str) -> bytes | None:
        row = self._connection.execute(
            "SELECT raw FROM kura_inbox WHERE delivery_id = ?",
            (delivery_id,),
        ).fetchone()
        return bytes(row["raw"]) if row else None

    def delivery_count(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS count FROM kura_inbox"
        ).fetchone()
        return int(row["count"])

    def _committed_record(
        self, delivery_id: str | None
    ) -> DeliveryCommitRecord | None:
        if delivery_id is None:
            return None
        row = self._connection.execute(
            """
            SELECT recipient, envelope_sha256, raw_sha256, raw_size
            FROM kura_inbox
            WHERE delivery_id = ?
            """,
            (delivery_id,),
        ).fetchone()
        if row is None:
            return None
        return DeliveryCommitRecord(
            recipient=str(row["recipient"]),
            envelope_sha256=str(row["envelope_sha256"]),
            raw_sha256=str(row["raw_sha256"]),
            raw_size=int(row["raw_size"]),
        )

    def _initialize(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS kura_inbox (
                delivery_id TEXT PRIMARY KEY,
                recipient TEXT NOT NULL,
                purpose TEXT NOT NULL,
                source_id TEXT NOT NULL,
                connector_release_id TEXT NOT NULL,
                media_type TEXT NOT NULL,
                envelope_sha256 TEXT NOT NULL,
                raw_sha256 TEXT NOT NULL,
                raw_size INTEGER NOT NULL CHECK(raw_size >= 0),
                envelope_json BLOB NOT NULL,
                raw BLOB NOT NULL,
                committed_at TEXT NOT NULL
            )
            """
        )


def _untrusted_delivery_id(envelope: dict[str, object]) -> str | None:
    delivery = envelope.get("delivery")
    if not isinstance(delivery, dict):
        return None
    value = delivery.get("id")
    return value if isinstance(value, str) and value else None
