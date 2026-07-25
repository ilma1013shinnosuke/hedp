from __future__ import annotations

from datetime import datetime
import gzip
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import BinaryIO


class CompressedBackupError(RuntimeError):
    """Raised when a compressed backup cannot be created or verified."""


_ARTIFACT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def _copy_and_hash(source: BinaryIO, destination: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while chunk := source.read(1024 * 1024):
        digest.update(chunk)
        size += len(chunk)
        destination.write(chunk)
    return digest.hexdigest(), size


def _hash_stream(source: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while chunk := source.read(1024 * 1024):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def create_verified_gzip(
    source_path: str | Path,
    destination_path: str | Path,
) -> dict[str, str | int]:
    """Create a verified gzip file without modifying the source.

    The compressed data is written to a private partial file on the same
    filesystem as the destination. The destination is replaced only after the
    decompressed checksum and size match the source.
    """

    source = Path(source_path)
    destination = Path(destination_path)
    if not source.is_file() or source.is_symlink():
        raise CompressedBackupError("source must be a regular file")
    if source.resolve() == destination.resolve():
        raise CompressedBackupError("source and destination must differ")

    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, partial_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".partial",
        dir=destination.parent,
    )
    partial = Path(partial_name)
    os.fchmod(descriptor, 0o600)

    try:
        with os.fdopen(descriptor, "wb") as raw_destination:
            with source.open("rb") as source_stream:
                with gzip.GzipFile(
                    filename="",
                    mode="wb",
                    fileobj=raw_destination,
                    compresslevel=6,
                    mtime=0,
                ) as compressed_stream:
                    source_sha256, source_size = _copy_and_hash(
                        source_stream,
                        compressed_stream,
                    )
            raw_destination.flush()
            os.fsync(raw_destination.fileno())

        with gzip.open(partial, "rb") as restored_stream:
            restored_sha256, restored_size = _hash_stream(restored_stream)
        if (restored_sha256, restored_size) != (source_sha256, source_size):
            raise CompressedBackupError(
                "compressed backup does not restore to the source content"
            )

        os.chmod(partial, 0o600)
        compressed_sha256 = _sha256_file(partial)
        compressed_size = partial.stat().st_size
        os.replace(partial, destination)
        return {
            "source_sha256": source_sha256,
            "source_size_bytes": source_size,
            "compressed_sha256": compressed_sha256,
            "compressed_size_bytes": compressed_size,
        }
    except (OSError, EOFError, gzip.BadGzipFile) as error:
        raise CompressedBackupError("compressed backup creation failed") from error
    finally:
        partial.unlink(missing_ok=True)


def verify_gzip(
    compressed_path: str | Path,
    *,
    expected_sha256: str | None = None,
    expected_size_bytes: int | None = None,
) -> dict[str, str | int]:
    """Verify that a gzip stream is readable and optionally matches metadata."""

    compressed = Path(compressed_path)
    try:
        with gzip.open(compressed, "rb") as restored_stream:
            restored_sha256, restored_size = _hash_stream(restored_stream)
    except (OSError, EOFError, gzip.BadGzipFile) as error:
        raise CompressedBackupError("compressed backup verification failed") from error

    if expected_sha256 is not None and restored_sha256 != expected_sha256:
        raise CompressedBackupError("restored checksum mismatch")
    if expected_size_bytes is not None and restored_size != expected_size_bytes:
        raise CompressedBackupError("restored size mismatch")
    return {
        "restored_sha256": restored_sha256,
        "restored_size_bytes": restored_size,
        "compressed_sha256": _sha256_file(compressed),
        "compressed_size_bytes": compressed.stat().st_size,
    }


def restore_and_verify_gzip_sqlite(
    compressed_path: str | Path,
    restored_path: str | Path,
    *,
    artifact_id: str,
    verified_at: datetime,
) -> dict[str, str | int]:
    """Restore an isolated SQLite backup and return a secret-free receipt."""

    compressed = Path(compressed_path)
    restored = Path(restored_path)
    if not compressed.is_file() or compressed.is_symlink():
        raise CompressedBackupError("compressed backup must be a regular file")
    if restored.exists() or restored.is_symlink():
        raise CompressedBackupError("restore destination already exists")
    if not isinstance(artifact_id, str) or not _ARTIFACT_ID.fullmatch(artifact_id):
        raise CompressedBackupError("artifact_id must be an opaque identifier")
    if (
        not isinstance(verified_at, datetime)
        or verified_at.tzinfo is None
        or verified_at.utcoffset() is None
    ):
        raise CompressedBackupError("verified_at must include a timezone")

    restored.parent.mkdir(parents=True, exist_ok=True)
    descriptor, partial_name = tempfile.mkstemp(
        prefix=f".{restored.name}.",
        suffix=".partial",
        dir=restored.parent,
    )
    partial = Path(partial_name)
    os.fchmod(descriptor, 0o600)
    published = False
    verified = False
    connection: sqlite3.Connection | None = None

    try:
        with os.fdopen(descriptor, "wb") as destination_stream:
            with gzip.open(compressed, "rb") as compressed_stream:
                while chunk := compressed_stream.read(1024 * 1024):
                    destination_stream.write(chunk)
            destination_stream.flush()
            os.fsync(destination_stream.fileno())

        os.link(partial, restored)
        published = True
        partial.unlink()
        os.chmod(restored, 0o600)

        connection = sqlite3.connect(
            f"{restored.resolve().as_uri()}?mode=ro",
            uri=True,
        )
        connection.execute("PRAGMA query_only=ON")
        quick_check = connection.execute("PRAGMA quick_check").fetchall()
        if quick_check != [("ok",)]:
            raise CompressedBackupError("restored database integrity check failed")
        connection.close()
        connection = None
        verified = True

        return {
            "artifact_id": artifact_id,
            "artifact_kind": "gzip_sqlite",
            "gzip": "ok",
            "outcome": "ok",
            "sqlite_quick_check": "ok",
            "verified_at": verified_at.isoformat(),
            "version": 1,
        }
    except CompressedBackupError:
        raise
    except (OSError, EOFError, gzip.BadGzipFile, sqlite3.Error) as error:
        raise CompressedBackupError("backup restore verification failed") from error
    finally:
        if connection is not None:
            connection.close()
        partial.unlink(missing_ok=True)
        if published and not verified:
            restored.unlink(missing_ok=True)
        if published:
            for suffix in ("-journal", "-wal", "-shm"):
                Path(f"{restored}{suffix}").unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        digest, _ = _hash_stream(stream)
    return digest
