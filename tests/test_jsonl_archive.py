from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hedp.storage.jsonl_archive import (
    ArchiveValidationError,
    create_jsonl_gzip_archive,
    iter_jsonl_gzip_archive,
    verify_jsonl_gzip_archive,
    verify_archive_matches_records,
)


def records() -> list[dict[str, object]]:
    return [
        {
            "observed_at": "2026-07-01T00:00:00+00:00",
            "raw_json": '{"value":1,"label":"日本語"}',
            "value": 1,
        },
        {
            "observed_at": "2026-07-01T00:01:00+00:00",
            "raw_json": '{"value":null}',
            "value": None,
        },
    ]


def create(directory: Path) -> dict[str, object]:
    return create_jsonl_gzip_archive(
        records(),
        directory,
        source="fixture",
        schema_name="fixture_rows",
        schema_version="1",
        timestamp_field="observed_at",
        created_by="test",
    )


def test_archive_round_trip_preserves_every_field(tmp_path: Path) -> None:
    destination = tmp_path / "fixture-2026-07.archive"
    manifest = create(destination)

    assert list(iter_jsonl_gzip_archive(destination)) == records()
    assert verify_jsonl_gzip_archive(destination) == manifest
    assert manifest["record_count"] == 2
    assert manifest["first_timestamp"] == "2026-07-01T00:00:00+00:00"
    assert manifest["last_timestamp"] == "2026-07-01T00:01:00+00:00"
    assert manifest["uncompressed_size_bytes"] > 0
    assert os.stat(destination).st_mode & 0o777 == 0o700
    assert os.stat(destination / "data.jsonl.gz").st_mode & 0o777 == 0o600
    assert os.stat(destination / "manifest.json").st_mode & 0o777 == 0o600


def test_archive_refuses_to_overwrite_existing_bundle(tmp_path: Path) -> None:
    destination = tmp_path / "fixture.archive"
    create(destination)

    with pytest.raises(FileExistsError):
        create(destination)


def test_archive_rejects_missing_timestamp_without_partial_output(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "fixture.archive"

    with pytest.raises(ArchiveValidationError):
        create_jsonl_gzip_archive(
            [{"value": 1}],
            destination,
            source="fixture",
            schema_name="fixture_rows",
            schema_version="1",
            timestamp_field="observed_at",
            created_by="test",
        )

    assert not destination.exists()
    assert not list(tmp_path.glob("*.partial"))


def test_archive_detects_compressed_data_tampering(tmp_path: Path) -> None:
    destination = tmp_path / "fixture.archive"
    create(destination)
    data = destination / "data.jsonl.gz"
    data.write_bytes(data.read_bytes() + b"tampered")

    with pytest.raises(
        ArchiveValidationError, match="compressed checksum mismatch"
    ):
        verify_jsonl_gzip_archive(destination)


def test_archive_detects_manifest_tampering(tmp_path: Path) -> None:
    destination = tmp_path / "fixture.archive"
    create(destination)
    path = destination / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["record_count"] = 3
    path.write_text(json.dumps(manifest))

    with pytest.raises(ArchiveValidationError, match="record_count mismatch"):
        verify_jsonl_gzip_archive(destination)


def test_archive_detects_uncompressed_size_tampering(tmp_path: Path) -> None:
    destination = tmp_path / "fixture.archive"
    create(destination)
    path = destination / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["uncompressed_size_bytes"] += 1
    path.write_text(json.dumps(manifest))

    with pytest.raises(
        ArchiveValidationError, match="uncompressed_size_bytes mismatch"
    ):
        verify_jsonl_gzip_archive(destination)


@pytest.mark.parametrize("name", ["manifest.json", "data.jsonl.gz"])
def test_archive_rejects_symlinked_bundle_file(
    tmp_path: Path,
    name: str,
) -> None:
    destination = tmp_path / "fixture.archive"
    create(destination)
    original = destination / name
    external = tmp_path / f"external-{name}"
    original.rename(external)
    original.symlink_to(external)

    with pytest.raises(ArchiveValidationError, match="non-symlink"):
        verify_jsonl_gzip_archive(destination)


def test_archive_rejects_symlinked_bundle_directory(tmp_path: Path) -> None:
    destination = tmp_path / "fixture.archive"
    create(destination)
    alias = tmp_path / "alias.archive"
    alias.symlink_to(destination, target_is_directory=True)

    with pytest.raises(ArchiveValidationError, match="non-symlink directory"):
        verify_jsonl_gzip_archive(alias)


def test_archive_requires_at_least_one_record(tmp_path: Path) -> None:
    destination = tmp_path / "fixture.archive"

    with pytest.raises(ArchiveValidationError, match="at least one"):
        create_jsonl_gzip_archive(
            [],
            destination,
            source="fixture",
            schema_name="fixture_rows",
            schema_version="1",
            timestamp_field="observed_at",
            created_by="test",
        )


def test_archive_compares_timestamps_as_instants(tmp_path: Path) -> None:
    destination = tmp_path / "fixture.archive"
    manifest = create_jsonl_gzip_archive(
        [
            {"observed_at": "2026-07-01T08:00:00+09:00"},
            {"observed_at": "2026-07-01T00:30:00+00:00"},
        ],
        destination,
        source="fixture",
        schema_name="fixture_rows",
        schema_version="1",
        timestamp_field="observed_at",
        created_by="test",
    )

    assert manifest["first_timestamp"] == "2026-07-01T08:00:00+09:00"
    assert manifest["last_timestamp"] == "2026-07-01T00:30:00+00:00"


def test_archive_rejects_timestamp_without_timezone(tmp_path: Path) -> None:
    with pytest.raises(ArchiveValidationError, match="include a timezone"):
        create_jsonl_gzip_archive(
            [{"observed_at": "2026-07-01T00:00:00"}],
            tmp_path / "fixture.archive",
            source="fixture",
            schema_name="fixture_rows",
            schema_version="1",
            timestamp_field="observed_at",
            created_by="test",
        )


def test_archive_must_match_current_source_records(tmp_path: Path) -> None:
    destination = tmp_path / "fixture.archive"
    create(destination)

    assert verify_archive_matches_records(destination, records())
    changed = records()
    changed[0]["value"] = 2
    with pytest.raises(ArchiveValidationError, match="source records"):
        verify_archive_matches_records(destination, changed)
