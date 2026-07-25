from __future__ import annotations

from datetime import datetime, timezone
import gzip
import sqlite3
import stat
from unittest.mock import patch

import pytest

from hedp.storage.compressed_backup import CompressedBackupError
from hedp.storage.compressed_backup import create_verified_gzip
from hedp.storage.compressed_backup import restore_and_verify_gzip_sqlite
from hedp.storage.compressed_backup import verify_gzip


def test_create_verified_gzip_is_lossless_atomic_and_keeps_source(tmp_path) -> None:
    source = tmp_path / "backup.db"
    source.write_bytes((b"sqlite fixture data\n" * 1024) + b"final")
    destination = tmp_path / "backup.db.gz"

    receipt = create_verified_gzip(source, destination)

    assert source.is_file()
    assert gzip.decompress(destination.read_bytes()) == source.read_bytes()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert list(tmp_path.glob(".*.partial")) == []
    assert receipt["source_size_bytes"] == source.stat().st_size
    assert verify_gzip(
        destination,
        expected_sha256=str(receipt["source_sha256"]),
        expected_size_bytes=int(receipt["source_size_bytes"]),
    )["restored_sha256"] == receipt["source_sha256"]


def test_failure_preserves_source_and_previous_destination(tmp_path) -> None:
    source = tmp_path / "backup.db"
    source.write_bytes(b"new backup")
    destination = tmp_path / "backup.db.gz"
    destination.write_bytes(b"previous verified backup")

    with patch(
        "hedp.storage.compressed_backup._hash_stream",
        side_effect=OSError("fixture failure"),
    ):
        with pytest.raises(CompressedBackupError):
            create_verified_gzip(source, destination)

    assert source.read_bytes() == b"new backup"
    assert destination.read_bytes() == b"previous verified backup"
    assert list(tmp_path.glob(".*.partial")) == []


def test_receipt_failure_happens_before_destination_replacement(tmp_path) -> None:
    source = tmp_path / "backup.db"
    source.write_bytes(b"new backup")
    destination = tmp_path / "backup.db.gz"
    destination.write_bytes(b"previous verified backup")

    with patch(
        "hedp.storage.compressed_backup._sha256_file",
        side_effect=OSError("fixture failure"),
    ):
        with pytest.raises(CompressedBackupError):
            create_verified_gzip(source, destination)

    assert source.read_bytes() == b"new backup"
    assert destination.read_bytes() == b"previous verified backup"
    assert list(tmp_path.glob(".*.partial")) == []


def test_verify_gzip_rejects_corruption_and_metadata_mismatch(tmp_path) -> None:
    invalid = tmp_path / "invalid.db.gz"
    invalid.write_bytes(b"not gzip")
    with pytest.raises(CompressedBackupError):
        verify_gzip(invalid)

    valid = tmp_path / "valid.db.gz"
    with gzip.open(valid, "wb") as stream:
        stream.write(b"fixture")
    with pytest.raises(CompressedBackupError, match="checksum"):
        verify_gzip(valid, expected_sha256="0" * 64)
    with pytest.raises(CompressedBackupError, match="size"):
        verify_gzip(valid, expected_size_bytes=999)


def test_source_must_be_regular_and_distinct(tmp_path) -> None:
    missing = tmp_path / "missing.db"
    with pytest.raises(CompressedBackupError, match="regular"):
        create_verified_gzip(missing, tmp_path / "backup.db.gz")

    source = tmp_path / "backup.db"
    source.write_bytes(b"fixture")
    with pytest.raises(CompressedBackupError, match="differ"):
        create_verified_gzip(source, source)


def test_restore_and_verify_gzip_sqlite_returns_safe_receipt(tmp_path) -> None:
    database = tmp_path / "synthetic.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE fixture (value TEXT NOT NULL)")
        connection.execute("INSERT INTO fixture VALUES ('fabricated')")
    compressed = tmp_path / "synthetic.db.gz"
    create_verified_gzip(database, compressed)
    original_compressed = compressed.read_bytes()
    database.unlink()
    restored = tmp_path / "isolated" / "restored.db"
    checked_at = datetime(2026, 7, 25, tzinfo=timezone.utc)

    receipt = restore_and_verify_gzip_sqlite(
        compressed,
        restored,
        artifact_id="fixture-v1",
        verified_at=checked_at,
    )

    assert receipt == {
        "artifact_id": "fixture-v1",
        "artifact_kind": "gzip_sqlite",
        "gzip": "ok",
        "outcome": "ok",
        "sqlite_quick_check": "ok",
        "verified_at": "2026-07-25T00:00:00+00:00",
        "version": 1,
    }
    assert stat.S_IMODE(restored.stat().st_mode) == 0o600
    assert compressed.read_bytes() == original_compressed
    assert list(restored.parent.glob(".*.partial")) == []
    with sqlite3.connect(restored) as connection:
        assert connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]


@pytest.mark.parametrize(
    "payload",
    [
        b"not gzip",
        gzip.compress(b"valid gzip but not sqlite"),
    ],
)
def test_restore_rejects_invalid_artifact_without_output(tmp_path, payload) -> None:
    compressed = tmp_path / "invalid.db.gz"
    compressed.write_bytes(payload)
    restored = tmp_path / "restored.db"

    with pytest.raises(CompressedBackupError):
        restore_and_verify_gzip_sqlite(
            compressed,
            restored,
            artifact_id="fixture-v1",
            verified_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
        )

    assert not restored.exists()
    assert list(tmp_path.glob(".*.partial")) == []


def test_restore_rejects_unsafe_metadata_and_existing_target(tmp_path) -> None:
    compressed = tmp_path / "backup.db.gz"
    compressed.write_bytes(gzip.compress(b"fixture"))
    restored = tmp_path / "restored.db"
    restored.write_bytes(b"existing")

    with pytest.raises(CompressedBackupError, match="already exists"):
        restore_and_verify_gzip_sqlite(
            compressed,
            restored,
            artifact_id="fixture-v1",
            verified_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
        )
    assert restored.read_bytes() == b"existing"

    restored.unlink()
    with pytest.raises(CompressedBackupError, match="opaque"):
        restore_and_verify_gzip_sqlite(
            compressed,
            restored,
            artifact_id="/private/backup/path",
            verified_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
        )
    with pytest.raises(CompressedBackupError, match="timezone"):
        restore_and_verify_gzip_sqlite(
            compressed,
            restored,
            artifact_id="fixture-v1",
            verified_at=datetime(2026, 7, 25),
        )


def test_restore_rejects_symlinked_input(tmp_path) -> None:
    compressed = tmp_path / "backup.db.gz"
    compressed.write_bytes(gzip.compress(b"fixture"))
    linked = tmp_path / "linked.db.gz"
    linked.symlink_to(compressed)

    with pytest.raises(CompressedBackupError, match="regular"):
        restore_and_verify_gzip_sqlite(
            linked,
            tmp_path / "restored.db",
            artifact_id="fixture-v1",
            verified_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
        )
