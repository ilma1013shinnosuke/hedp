from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ElementTree
import zipfile
from zoneinfo import ZoneInfo

from hedp.raw_data import RawData
from hedp.record import Record
from hedp.storage import Storage


SOURCE = "fusionsolar_station_report"
TOKYO = ZoneInfo("Asia/Tokyo")
NAMESPACE = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
METRICS = {
    "合計PV容量（kWp）": ("installedCapacity", "kWp"),
    "全体日射量（kWh/m²）": ("irradiation", "kWh/m²"),
    "日照時間(h)": ("sunshineHours", "h"),
    "平均温度(℃)": ("averageTemperature", "°C"),
    "理論的発電量(kWh)": ("theoreticalEnergy", "kWh"),
    "PV入力量(kWh)": ("pvInputEnergy", "kWh"),
    "PCS出力量(kWh)": ("inverterOutputEnergy", "kWh"),
    "累計発電量（kWh）": ("cumulativeEnergy", "kWh"),
    "エクスポート（kWh）": ("exportEnergy", "kWh"),
    "買電電力量（kWh）": ("purchasedEnergy", "kWh"),
    "当日等価システム稼働時間(kWh/kWp)": (
        "equivalentSystemHours", "kWh/kWp"
    ),
    "抑制による損失(kwh)": ("curtailmentLoss", "kWh"),
    "エクスポート制限による損失(￥)": ("exportLimitLoss", "JPY"),
    "負荷消費電力（kWh）": ("loadConsumptionEnergy", "kWh"),
    "自家消費量(kWh)": ("selfConsumptionEnergy", "kWh"),
    "自己消費率（%）": ("selfConsumptionRatio", "%"),
    "ピーク電力(kW)": ("peakPower", "kW"),
    "パフォーマンス率（%）": ("performanceRatio", "%"),
    "CO₂削減量（t）": ("co2Reduction", "t"),
    "石炭節約量（t）": ("coalSavings", "t"),
    "充電(kWh)": ("chargeEnergy", "kWh"),
    "放電(kWh)": ("dischargeEnergy", "kWh"),
    "収益(￥)": ("revenue", "JPY"),
}


class FusionSolarReportImporter:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def inspect(self, path: Path) -> dict[str, Any]:
        return self._report(path, dry_run=True, write=False)

    def run(self, path: Path, *, dry_run: bool = False) -> dict[str, Any]:
        return self._report(path, dry_run=dry_run, write=not dry_run)

    def _report(
        self, path: Path, *, dry_run: bool, write: bool
    ) -> dict[str, Any]:
        files = sorted(path.glob("*.xlsx")) if path.is_dir() else [path]
        ignored = (
            sorted(str(item) for item in path.iterdir() if item.suffix != ".xlsx")
            if path.is_dir()
            else []
        )
        existing = {
            (item.timestamp.isoformat(), item.metric): item
            for item in self.storage.load_records()
            if item.source == SOURCE
        }
        reports = []
        pending: list[Record] = []
        raw_items: list[RawData] = []
        total_conflicts = 0
        for file_path in files:
            rows, invalid = self._rows(file_path)
            inserted = duplicates = conflicts = values = 0
            records: list[Record] = []
            for row in rows:
                for record in self._records(row):
                    values += 1
                    key = (record.timestamp.isoformat(), record.metric)
                    previous = existing.get(key)
                    if previous is None:
                        inserted += 1
                        existing[key] = record
                        records.append(record)
                    elif previous.value == record.value and previous.unit == record.unit:
                        duplicates += 1
                    else:
                        conflicts += 1
            total_conflicts += conflicts
            pending.extend(records)
            if rows:
                raw_items.append(RawData(
                    source=SOURCE,
                    timestamp=datetime.now(timezone.utc),
                    target_date=datetime.fromisoformat(rows[0]["検索時間"]).date(),
                    payload={"rows": rows},
                    metadata={
                        "source_file": file_path.name,
                        "sha256": self._hash(file_path),
                    },
                ))
            reports.append({
                "path": str(file_path), "rows": len(rows), "invalid_rows": invalid,
                "values": values, "rows_inserted": inserted,
                "duplicates_skipped": duplicates, "conflicts": conflicts,
                "sha256": self._hash(file_path),
            })
        status = "blocked" if total_conflicts else "dry_run" if dry_run else "completed"
        if write and not total_conflicts:
            for item in raw_items:
                self.storage.save_rawdata(item)
            connection = self.storage._require_connection()
            connection.executemany(
                "INSERT INTO records (data) VALUES (?)",
                [(item.to_json(),) for item in pending],
            )
            connection.commit()
        return {
            "status": status, "files": reports, "ignored": ignored,
            "rows_inserted": sum(item["rows_inserted"] for item in reports),
            "duplicates_skipped": sum(
                item["duplicates_skipped"] for item in reports
            ),
            "conflicts": total_conflicts,
        }

    @staticmethod
    def _records(row: dict[str, str]) -> list[Record]:
        local = datetime.fromisoformat(row["検索時間"]).replace(tzinfo=TOKYO)
        timestamp = local.astimezone(timezone.utc)
        records = []
        for header, (metric, unit) in METRICS.items():
            value = row.get(header, "").strip()
            if not value:
                continue
            records.append(Record(SOURCE, timestamp, metric, float(value), unit))
        return records

    @staticmethod
    def _rows(path: Path) -> tuple[list[dict[str, str]], int]:
        with zipfile.ZipFile(path) as archive:
            shared: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                root = ElementTree.parse(
                    archive.open("xl/sharedStrings.xml")
                ).getroot()
                for item in root.findall(f"{NAMESPACE}si"):
                    shared.append("".join(
                        node.text or "" for node in item.iter(f"{NAMESPACE}t")
                    ))
            root = ElementTree.parse(
                archive.open("xl/worksheets/sheet1.xml")
            ).getroot()
        table = []
        for row in root.iter(f"{NAMESPACE}row"):
            values: dict[int, str] = {}
            for cell in row.findall(f"{NAMESPACE}c"):
                reference = cell.get("r", "A1")
                letters = "".join(char for char in reference if char.isalpha())
                index = 0
                for char in letters:
                    index = index * 26 + ord(char) - 64
                inline = cell.find(f"{NAMESPACE}is")
                value = cell.find(f"{NAMESPACE}v")
                if inline is not None:
                    text = "".join(
                        node.text or "" for node in inline.iter(f"{NAMESPACE}t")
                    )
                elif value is None or value.text is None:
                    text = ""
                elif cell.get("t") == "s":
                    text = shared[int(value.text)]
                else:
                    text = value.text
                values[index] = text
            table.append(values)
        header_row = next(
            (item for item in table if item.get(1) == "検索時間"), None
        )
        if header_row is None:
            raise ValueError(f"Header row not found in {path.name}")
        headers = {index: value for index, value in header_row.items()}
        rows = []
        invalid = 0
        header_seen = False
        for values in table:
            if values is header_row:
                header_seen = True
                continue
            if not header_seen or not values.get(1):
                continue
            row = {header: values.get(index, "") for index, header in headers.items()}
            try:
                datetime.fromisoformat(row["検索時間"])
                FusionSolarReportImporter._records(row)
            except (KeyError, ValueError):
                invalid += 1
                continue
            rows.append(row)
        return rows, invalid

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
