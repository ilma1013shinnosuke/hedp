from __future__ import annotations

import gzip

import pytest

from hedp.storage.compressed_backup import CompressedBackupError
from scripts.compress_verified_backup import compress_verified_backup
from scripts.compress_verified_backup import main


def test_command_creates_verified_gzip_and_removes_source(tmp_path) -> None:
    source = tmp_path / "backup.db"
    source.write_bytes(b"synthetic backup")

    compress_verified_backup(source, remove_source=True)

    assert not source.exists()
    assert gzip.decompress((tmp_path / "backup.db.gz").read_bytes()) == (
        b"synthetic backup"
    )


def test_command_is_idempotent_after_source_deletion_failure(tmp_path) -> None:
    source = tmp_path / "backup.db"
    source.write_bytes(b"synthetic backup")
    compress_verified_backup(source, remove_source=False)
    existing = (tmp_path / "backup.db.gz").read_bytes()

    compress_verified_backup(source, remove_source=True)

    assert not source.exists()
    assert (tmp_path / "backup.db.gz").read_bytes() == existing


def test_command_preserves_mismatched_source_and_destination(tmp_path) -> None:
    source = tmp_path / "backup.db"
    source.write_bytes(b"new synthetic backup")
    destination = tmp_path / "backup.db.gz"
    destination.write_bytes(gzip.compress(b"previous synthetic backup"))

    with pytest.raises(CompressedBackupError):
        compress_verified_backup(source, remove_source=True)

    assert source.read_bytes() == b"new synthetic backup"
    assert gzip.decompress(destination.read_bytes()) == b"previous synthetic backup"


def test_cli_failure_message_contains_no_path_or_exception_detail(
    tmp_path,
    capsys,
) -> None:
    missing = tmp_path / "private-name.db"

    assert main([str(missing), "--remove-source"]) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "verified backup compression failed\n"
    assert "private-name" not in output.err
