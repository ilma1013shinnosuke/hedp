from pathlib import Path
import zipfile

from hedp.adapters.fusionsolar.report_importer import (
    FusionSolarReportImporter,
    SOURCE,
)
from hedp.storage import Storage


def _workbook(path: Path, value: str = "12.5") -> None:
    headers = ["検索時間", "負荷消費電力（kWh）", "充電(kWh)"]
    rows = [headers, ["2025-03-01", value, "2.25"]]
    xml_rows = []
    for row_number, row in enumerate(rows, 1):
        cells = "".join(
            f'<c r="{chr(65 + index)}{row_number}" t="inlineStr">'
            f"<is><t>{item}</t></is></c>"
            for index, item in enumerate(row)
        )
        xml_rows.append(f'<row r="{row_number}">{cells}</row>')
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/'
        'spreadsheetml/2006/main"><sheetData>'
        + "".join(xml_rows)
        + "</sheetData></worksheet>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)


def _storage(tmp_path: Path) -> Storage:
    storage = Storage(str(tmp_path / "hedp.db"))
    storage.connect()
    return storage


def test_report_import_is_audited_and_idempotent(tmp_path):
    report_path = tmp_path / "発電所レポート_2025-03.xlsx"
    _workbook(report_path)
    storage = _storage(tmp_path)
    try:
        importer = FusionSolarReportImporter(storage)
        dry_run = importer.run(tmp_path, dry_run=True)
        first = importer.run(tmp_path)
        second = importer.run(tmp_path)
        records = [item for item in storage.load_records() if item.source == SOURCE]
        raw_data = [item for item in storage.load_rawdata() if item.source == SOURCE]
    finally:
        storage._require_connection().close()

    assert dry_run["rows_inserted"] == 2
    assert first["status"] == "completed"
    assert first["rows_inserted"] == 2
    assert second["rows_inserted"] == 0
    assert second["duplicates_skipped"] == 2
    assert {item.metric for item in records} == {
        "loadConsumptionEnergy", "chargeEnergy"
    }
    assert len(raw_data) == 1
    assert raw_data[0].metadata["source_file"] == report_path.name


def test_report_import_blocks_changed_value(tmp_path):
    report_path = tmp_path / "発電所レポート_2025-03.xlsx"
    _workbook(report_path)
    storage = _storage(tmp_path)
    try:
        importer = FusionSolarReportImporter(storage)
        assert importer.run(tmp_path)["rows_inserted"] == 2
        _workbook(report_path, "99")
        report = importer.run(tmp_path)
        records = [item for item in storage.load_records() if item.source == SOURCE]
    finally:
        storage._require_connection().close()

    assert report["status"] == "blocked"
    assert report["conflicts"] == 1
    assert len(records) == 2
