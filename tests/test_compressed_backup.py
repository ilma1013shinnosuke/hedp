from __future__ import annotations

import gzip
import stat
from unittest.mock import patch

import pytest

from hedp.storage.compressed_backup import CompressedBackupError
from hedp.storage.compressed_backup import create_verified_gzip
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
