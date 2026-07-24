from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ARCHIVE_FORMAT_VERSION = 1
DATA_FILENAME = "data.jsonl.gz"
MANIFEST_FILENAME = "manifest.json"


class ArchiveValidationError(ValueError):
    """Raised when an archive cannot be proven to match its manifest."""


def _json_line(record: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            dict(record),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp_key(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ArchiveValidationError(
            f"record field {field!r} must use ISO 8601"
        ) from error
    if parsed.tzinfo is None:
        raise ArchiveValidationError(
            f"record field {field!r} must include a timezone"
        )
    return parsed.astimezone(timezone.utc)


def create_jsonl_gzip_archive(
    records: Iterable[Mapping[str, Any]],
    destination: str | Path,
    *,
    source: str,
    schema_name: str,
    schema_version: str,
    timestamp_field: str,
    created_by: str,
) -> dict[str, Any]:
    """Create an atomic, lossless JSON Lines gzip archive bundle."""

    final_directory = Path(destination)
    if final_directory.exists():
        raise FileExistsError(final_directory)
    final_directory.parent.mkdir(parents=True, exist_ok=True)
    temporary_directory = Path(
        tempfile.mkdtemp(
            prefix=f".{final_directory.name}.",
            suffix=".partial",
            dir=final_directory.parent,
        )
    )
    os.chmod(temporary_directory, 0o700)
    data_path = temporary_directory / DATA_FILENAME
    manifest_path = temporary_directory / MANIFEST_FILENAME
    content_digest = hashlib.sha256()
    count = 0
    first_timestamp: str | None = None
    last_timestamp: str | None = None
    first_timestamp_key: datetime | None = None
    last_timestamp_key: datetime | None = None

    try:
        with data_path.open("wb") as raw_stream:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                compresslevel=6,
                fileobj=raw_stream,
                mtime=0,
            ) as compressed_stream:
                for record in records:
                    timestamp = record.get(timestamp_field)
                    if not isinstance(timestamp, str) or not timestamp:
                        raise ArchiveValidationError(
                            f"record requires string field {timestamp_field!r}"
                        )
                    timestamp_key = _timestamp_key(timestamp, timestamp_field)
                    line = _json_line(record)
                    content_digest.update(line)
                    compressed_stream.write(line)
                    count += 1
                    if (
                        first_timestamp_key is None
                        or timestamp_key < first_timestamp_key
                    ):
                        first_timestamp = timestamp
                        first_timestamp_key = timestamp_key
                    if (
                        last_timestamp_key is None
                        or timestamp_key > last_timestamp_key
                    ):
                        last_timestamp = timestamp
                        last_timestamp_key = timestamp_key
        os.chmod(data_path, 0o600)
        if count == 0:
            raise ArchiveValidationError("an archive must contain at least one record")

        manifest = {
            "format_version": ARCHIVE_FORMAT_VERSION,
            "content_type": "application/x-ndjson",
            "compression": "gzip",
            "source": source,
            "schema_name": schema_name,
            "schema_version": schema_version,
            "timestamp_field": timestamp_field,
            "record_count": count,
            "first_timestamp": first_timestamp,
            "last_timestamp": last_timestamp,
            "uncompressed_sha256": content_digest.hexdigest(),
            "compressed_sha256": _sha256_file(data_path),
            "compressed_size_bytes": data_path.stat().st_size,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": created_by,
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)
            + "\n",
            encoding="utf-8",
        )
        os.chmod(manifest_path, 0o600)
        verify_jsonl_gzip_archive(temporary_directory)
        os.replace(temporary_directory, final_directory)
        return manifest
    except BaseException:
        shutil.rmtree(temporary_directory, ignore_errors=True)
        raise


def load_archive_manifest(directory: str | Path) -> dict[str, Any]:
    manifest_path = Path(directory) / MANIFEST_FILENAME
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ArchiveValidationError("manifest must be a JSON object")
    return value


def iter_jsonl_gzip_archive(
    directory: str | Path,
) -> Iterator[dict[str, Any]]:
    data_path = Path(directory) / DATA_FILENAME
    with gzip.open(data_path, "rt", encoding="utf-8", newline="") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ArchiveValidationError(
                    f"invalid JSON at archive line {line_number}"
                ) from error
            if not isinstance(value, dict):
                raise ArchiveValidationError(
                    f"archive line {line_number} must be a JSON object"
                )
            yield value


def verify_jsonl_gzip_archive(directory: str | Path) -> dict[str, Any]:
    archive_directory = Path(directory)
    manifest = load_archive_manifest(archive_directory)
    required = {
        "format_version",
        "compression",
        "timestamp_field",
        "record_count",
        "first_timestamp",
        "last_timestamp",
        "uncompressed_sha256",
        "compressed_sha256",
    }
    missing = sorted(required - manifest.keys())
    if missing:
        raise ArchiveValidationError(
            f"archive manifest is missing fields: {', '.join(missing)}"
        )
    if manifest["format_version"] != ARCHIVE_FORMAT_VERSION:
        raise ArchiveValidationError("unsupported archive format version")
    if manifest["compression"] != "gzip":
        raise ArchiveValidationError("unsupported archive compression")

    data_path = archive_directory / DATA_FILENAME
    if _sha256_file(data_path) != manifest["compressed_sha256"]:
        raise ArchiveValidationError("compressed checksum mismatch")

    timestamp_field = manifest["timestamp_field"]
    if not isinstance(timestamp_field, str) or not timestamp_field:
        raise ArchiveValidationError("invalid timestamp field")
    digest = hashlib.sha256()
    count = 0
    first_timestamp: str | None = None
    last_timestamp: str | None = None
    first_timestamp_key: datetime | None = None
    last_timestamp_key: datetime | None = None
    for record in iter_jsonl_gzip_archive(archive_directory):
        timestamp = record.get(timestamp_field)
        if not isinstance(timestamp, str) or not timestamp:
            raise ArchiveValidationError(
                f"record requires string field {timestamp_field!r}"
            )
        timestamp_key = _timestamp_key(timestamp, timestamp_field)
        digest.update(_json_line(record))
        count += 1
        if first_timestamp_key is None or timestamp_key < first_timestamp_key:
            first_timestamp = timestamp
            first_timestamp_key = timestamp_key
        if last_timestamp_key is None or timestamp_key > last_timestamp_key:
            last_timestamp = timestamp
            last_timestamp_key = timestamp_key

    checks = {
        "record_count": count,
        "first_timestamp": first_timestamp,
        "last_timestamp": last_timestamp,
        "uncompressed_sha256": digest.hexdigest(),
    }
    for field, actual in checks.items():
        if actual != manifest[field]:
            raise ArchiveValidationError(f"{field} mismatch")
    return manifest
