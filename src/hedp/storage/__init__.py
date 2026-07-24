"""取得した事実と利用可能なデータを保存する。"""

from .database import Storage
from .jsonl_archive import (
    ArchiveValidationError,
    create_jsonl_gzip_archive,
    iter_jsonl_gzip_archive,
    verify_archive_matches_records,
    verify_jsonl_gzip_archive,
)
from .raw_data import RawData
from .record import Record

__all__ = [
    "ArchiveValidationError",
    "RawData",
    "Record",
    "Storage",
    "create_jsonl_gzip_archive",
    "iter_jsonl_gzip_archive",
    "verify_archive_matches_records",
    "verify_jsonl_gzip_archive",
]
