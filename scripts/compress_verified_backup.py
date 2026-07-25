#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from hedp.storage.compressed_backup import CompressedBackupError
from hedp.storage.compressed_backup import create_verified_gzip
from hedp.storage.compressed_backup import verify_gzip_matches_file


def compress_verified_backup(
    source_path: str | Path,
    *,
    remove_source: bool,
) -> None:
    """Create or verify SOURCE.gz and optionally remove the verified source."""

    source = Path(source_path)
    destination = Path(f"{source}.gz")
    if destination.exists() or destination.is_symlink():
        verify_gzip_matches_file(source, destination)
    else:
        create_verified_gzip(source, destination)
    if remove_source:
        source.unlink()


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a lossless, verified gzip backup.",
    )
    parser.add_argument("source")
    parser.add_argument("--remove-source", action="store_true")
    parsed = parser.parse_args(arguments)
    try:
        compress_verified_backup(
            parsed.source,
            remove_source=parsed.remove_source,
        )
    except (CompressedBackupError, OSError):
        print("verified backup compression failed", file=sys.stderr)
        return 1
    print("verified backup compression completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
