"""Durable HESTIA-owned Inbox for accepted public KURA deliveries."""

from __future__ import annotations

import os
import sqlite3
import uuid
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


class AcknowledgementConflictError(RuntimeError):
    """An ACK completion did not match the durable pending binding."""


@dataclass(frozen=True)
class AcknowledgementIntent:
    """ACK data durably stored with an accepted delivery."""

    app_commit_id: str
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
            app_commit_id = f"hestia-kura-{uuid.uuid4().hex}"
            self._connection.execute(
                """
                INSERT INTO kura_inbox (
                    delivery_id, app_commit_id, recipient, purpose, source_id,
                    connector_release_id, media_type, envelope_sha256,
                    raw_sha256, raw_size, envelope_json, raw, committed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conformance.delivery_id,
                    app_commit_id,
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
            self._connection.execute(
                """
                INSERT INTO kura_ack_outbox (
                    delivery_id, app_commit_id, recipient, envelope_sha256,
                    raw_sha256, raw_size, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    conformance.delivery_id,
                    app_commit_id,
                    delivery["recipient"],
                    provided_envelope_sha256,
                    conformance.commit_record.raw_sha256,
                    conformance.commit_record.raw_size,
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
                app_commit_id=app_commit_id,
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

    def pending_acknowledgements(
        self, *, limit: int = 100
    ) -> tuple[AcknowledgementIntent, ...]:
        """Return durable pending ACK intents in commit order."""

        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 10_000
        ):
            raise ValueError("limit must be between 1 and 10000")
        rows = self._connection.execute(
            """
            SELECT app_commit_id, delivery_id, recipient, envelope_sha256,
                   raw_sha256, raw_size, created_at
            FROM kura_ack_outbox
            WHERE status = 'pending'
            ORDER BY created_at, delivery_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return tuple(_acknowledgement_intent(row) for row in rows)

    def mark_acknowledged(
        self,
        acknowledgement: AcknowledgementIntent,
        *,
        acknowledged_at: datetime | None = None,
    ) -> bool:
        """Mark a matching pending ACK complete; return True if already complete."""

        completed_at = acknowledged_at or datetime.now(UTC)
        if completed_at.tzinfo is None or completed_at.utcoffset() is None:
            raise ValueError("acknowledged_at must be timezone-aware")
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            row = self._connection.execute(
                """
                SELECT app_commit_id, delivery_id, recipient, envelope_sha256,
                       raw_sha256, raw_size, status
                FROM kura_ack_outbox
                WHERE delivery_id = ?
                """,
                (acknowledgement.delivery_id,),
            ).fetchone()
            if row is None:
                raise AcknowledgementConflictError(
                    "ACK delivery has no durable pending binding"
                )
            if not _matches_acknowledgement(row, acknowledgement):
                raise AcknowledgementConflictError(
                    "ACK values do not match the durable pending binding"
                )
            if row["status"] == "acknowledged":
                self._connection.rollback()
                return True
            if row["status"] != "pending":
                raise AcknowledgementConflictError("ACK state is invalid")
            self._connection.execute(
                """
                UPDATE kura_ack_outbox
                SET status = 'acknowledged', acknowledged_at = ?
                WHERE delivery_id = ? AND status = 'pending'
                """,
                (completed_at.isoformat(), acknowledgement.delivery_id),
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return False

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
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS kura_inbox (
                    delivery_id TEXT PRIMARY KEY,
                    app_commit_id TEXT NOT NULL UNIQUE,
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
            columns = {
                str(row["name"])
                for row in self._connection.execute(
                    "PRAGMA table_info(kura_inbox)"
                ).fetchall()
            }
            if "app_commit_id" not in columns:
                self._connection.execute(
                    "ALTER TABLE kura_inbox ADD COLUMN app_commit_id TEXT"
                )
            rows = self._connection.execute(
                """
                SELECT delivery_id, recipient, envelope_sha256,
                       raw_sha256, raw_size
                FROM kura_inbox
                WHERE app_commit_id IS NULL
                """
            ).fetchall()
            for row in rows:
                self._connection.execute(
                    """
                    UPDATE kura_inbox
                    SET app_commit_id = ?
                    WHERE delivery_id = ?
                    """,
                    (_legacy_app_commit_id(row), row["delivery_id"]),
                )
            self._connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                    kura_inbox_app_commit_id_unique
                ON kura_inbox(app_commit_id)
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS kura_ack_outbox (
                    delivery_id TEXT PRIMARY KEY,
                    app_commit_id TEXT NOT NULL UNIQUE,
                    recipient TEXT NOT NULL,
                    envelope_sha256 TEXT NOT NULL,
                    raw_sha256 TEXT NOT NULL,
                    raw_size INTEGER NOT NULL CHECK(raw_size >= 0),
                    status TEXT NOT NULL
                        CHECK(status IN ('pending', 'acknowledged')),
                    created_at TEXT NOT NULL,
                    acknowledged_at TEXT,
                    FOREIGN KEY(delivery_id)
                        REFERENCES kura_inbox(delivery_id)
                )
                """
            )
            self._connection.execute(
                """
                INSERT OR IGNORE INTO kura_ack_outbox (
                    delivery_id, app_commit_id, recipient, envelope_sha256,
                    raw_sha256, raw_size, status, created_at
                )
                SELECT delivery_id, app_commit_id, recipient, envelope_sha256,
                       raw_sha256, raw_size, 'pending', committed_at
                FROM kura_inbox
                """
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise


def _untrusted_delivery_id(envelope: dict[str, object]) -> str | None:
    delivery = envelope.get("delivery")
    if not isinstance(delivery, dict):
        return None
    value = delivery.get("id")
    return value if isinstance(value, str) and value else None


def _acknowledgement_intent(row: sqlite3.Row) -> AcknowledgementIntent:
    return AcknowledgementIntent(
        app_commit_id=str(row["app_commit_id"]),
        delivery_id=str(row["delivery_id"]),
        recipient=str(row["recipient"]),
        envelope_sha256=str(row["envelope_sha256"]),
        raw_sha256=str(row["raw_sha256"]),
        raw_size=int(row["raw_size"]),
        committed_at=datetime.fromisoformat(str(row["created_at"])),
    )


def _matches_acknowledgement(
    row: sqlite3.Row, acknowledgement: AcknowledgementIntent
) -> bool:
    return (
        row["app_commit_id"] == acknowledgement.app_commit_id
        and row["delivery_id"] == acknowledgement.delivery_id
        and row["recipient"] == acknowledgement.recipient
        and row["envelope_sha256"] == acknowledgement.envelope_sha256
        and row["raw_sha256"] == acknowledgement.raw_sha256
        and row["raw_size"] == acknowledgement.raw_size
    )


def _legacy_app_commit_id(row: sqlite3.Row) -> str:
    binding = "\0".join(
        (
            str(row["delivery_id"]),
            str(row["recipient"]),
            str(row["envelope_sha256"]),
            str(row["raw_sha256"]),
            str(row["raw_size"]),
        )
    )
    return f"hestia-kura-legacy-{uuid.uuid5(uuid.NAMESPACE_URL, binding).hex}"
