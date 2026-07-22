import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hedp.adapters.fusionsolar.gas_queue_importer import (
    FusionSolarGasQueueImporter,
    GasQueueError,
)
from hedp.storage import Storage


def queue_file(folder: Path, payload=None, **changes) -> Path:
    payload = payload or {
        "data": {"list": [{"fmtCollectTimeStr": "2026-07-21 12:00:00", "productPower": 1.2}]}
    }
    payload_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(payload_text.encode()).hexdigest()
    envelope = {
        "schema_version": 2,
        "source": "fusionsolar",
        "collected_at": "2026-07-21T13:00:00.000Z",
        "target_date": "2026-07-21",
        "request": {
            "method": "POST",
            "endpoint": "/rest/pvms/web/report/v1/station/station-kpi-list",
            "statDim": "2",
        },
        "payload_sha256": digest,
        "payload_text": payload_text,
    }
    envelope.update(changes)
    path = folder / f"fusionsolar_2026-07-21_{digest[:16]}.json"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    return path


def test_inspect_is_filesystem_only_and_safe(tmp_path):
    queue_file(tmp_path)
    report = FusionSolarGasQueueImporter().inspect(tmp_path)
    assert report["status"] == "inspected"
    assert report["ready_to_import"] == 1
    rendered = json.dumps(report)
    assert "payload_text" not in rendered
    assert "fmtCollectTimeStr" not in rendered


def test_write_is_atomic_and_idempotent(tmp_path):
    queue_file(tmp_path)
    storage = Storage(str(tmp_path / "hedp.sqlite3"))
    connection = storage.connect()
    importer = FusionSolarGasQueueImporter(storage)
    assert importer.run(tmp_path)["status"] == "completed"
    assert storage.count_rawdata() == 1
    report = importer.run(tmp_path)
    assert report["duplicates_skipped"] == 1
    assert storage.count_rawdata() == 1
    assert connection.execute("SELECT count(*) FROM gas_import_receipts").fetchone()[0] == 1


def test_dry_run_does_not_create_receipt_table(tmp_path):
    queue_file(tmp_path)
    storage = Storage(str(tmp_path / "hedp.sqlite3"))
    connection = storage.connect()
    assert FusionSolarGasQueueImporter(storage).run(tmp_path, dry_run=True)["status"] == "dry_run"
    assert connection.execute(
        "SELECT count(*) FROM sqlite_master WHERE name='gas_import_receipts'"
    ).fetchone()[0] == 0
    assert storage.count_rawdata() == 0


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"payload_sha256": "0" * 64}, "payload_hash_mismatch"),
        ({"schema_version": 1}, "invalid_envelope_schema"),
        ({"collected_at": datetime.now(timezone.utc).isoformat()}, "collected_at_not_utc"),
        ({"request": {"method": "DELETE"}}, "request_not_allowed"),
    ],
)
def test_invalid_envelopes_are_rejected(tmp_path, change, reason):
    queue_file(tmp_path, **change)
    with pytest.raises(GasQueueError, match=reason):
        FusionSolarGasQueueImporter().inspect(tmp_path)


def test_symlink_is_rejected(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    file = queue_file(real)
    link = tmp_path / file.name
    link.symlink_to(file)
    with pytest.raises(GasQueueError, match="symlink_not_allowed"):
        FusionSolarGasQueueImporter().inspect(link)


def test_same_day_different_payload_is_blocked(tmp_path):
    queue_file(tmp_path)
    first = next(tmp_path.glob("*.json"))
    alternate = {"data": {"list": [{"fmtCollectTimeStr": "2026-07-21 13:00:00", "productPower": 2.0}]}}
    payload_text = json.dumps(alternate, separators=(",", ":"))
    digest = hashlib.sha256(payload_text.encode()).hexdigest()
    envelope = json.loads(first.read_text())
    envelope["payload_text"] = payload_text
    envelope["payload_sha256"] = digest
    (tmp_path / f"fusionsolar_2026-07-21_{digest[:16]}.json").write_text(json.dumps(envelope))
    with pytest.raises(GasQueueError, match="same_day_payload_conflict"):
        FusionSolarGasQueueImporter().inspect(tmp_path)
